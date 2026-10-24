"""Quizzes core tests (Module 1).

These tests mock the service layer to avoid a real DB and focus on HTTP behavior,
RBAC, canonical errors, and SSE heartbeat visibility.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.jwt import generate_token
from app.main import app
from app.utils.errors import (
    AUTH403_FORBIDDEN,
    QZ404_SESSION_NOT_FOUND,
    QZ409_DUPLICATE_ANSWER,
)


@pytest.mark.asyncio
async def test_start_requires_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/quizzes/start", json={"topic_name": "Algebra"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_start_quiz_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock service.start_quiz
    result = {
        "session": {
            "session_uid": "01HVX2A6K9E2E8Q6R1Z4JY3N7X",
            "quiz_uid": "01HVX2A6K9E2E8Q6R1Z4JY3N7Y",
            "topic_id": None,
            "current_difficulty": 3,
            "needs_refill": False,
        },
        "first_question": None,
    }

    import app.features.quizzes.router as R
    async def _start_quiz(**kwargs):  # type: ignore[no-redef]
        return result
    monkeypatch.setattr(R._service, "start_quiz", _start_quiz)

    token = generate_token(subject="00000000-0000-0000-0000-000000000001", role="user")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        r = await client.post("/quizzes/start", json={"topic_name": "Algebra"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["session"]["current_difficulty"] == 3


@pytest.mark.asyncio
async def test_answer_duplicate_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.features.quizzes.router as R

    async def _submit_answer(**kwargs):  # type: ignore[no-redef]
        from app.utils.errors import AppError
        raise AppError("duplicate answer", code=QZ409_DUPLICATE_ANSWER, status=409)

    monkeypatch.setattr(R._service, "submit_answer", _submit_answer)

    token = generate_token(subject="00000000-0000-0000-0000-000000000001", role="user")
    payload = {"question_id": "00000000-0000-0000-0000-0000000000aa", "selected_answer": "A"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        r = await client.post("/quizzes/01S3SSION/answer", json=payload)
        assert r.status_code == 409
        body = r.json()
        assert body["error"]["code"] == QZ409_DUPLICATE_ANSWER


@pytest.mark.asyncio
async def test_summary_session_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.features.quizzes.router as R

    async def _summarize_session(**kwargs):  # type: ignore[no-redef]
        from app.utils.errors import AppError
        raise AppError("not found", code=QZ404_SESSION_NOT_FOUND, status=404)

    monkeypatch.setattr(R._service, "summarize_session", _summarize_session)

    token = generate_token(subject="00000000-0000-0000-0000-000000000001", role="user")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        r = await client.get("/quizzes/NOPE/summary")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == QZ404_SESSION_NOT_FOUND


@pytest.mark.asyncio
async def test_answer_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.features.quizzes.router as R

    async def _submit_answer(**kwargs):  # type: ignore[no-redef]
        from app.utils.errors import AppError
        raise AppError("forbidden", code=AUTH403_FORBIDDEN, status=403)

    monkeypatch.setattr(R._service, "submit_answer", _submit_answer)

    token = generate_token(subject="00000000-0000-0000-0000-000000000001", role="user")
    payload = {"question_id": "00000000-0000-0000-0000-0000000000aa", "selected_answer": "B"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        r = await client.post("/quizzes/01S3SSION/answer", json=payload)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == AUTH403_FORBIDDEN


@pytest.mark.asyncio
async def test_sse_heartbeat_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the SSE endpoint streams heartbeats.

    We lower the heartbeat interval to 1s for this test.
    """
    # Force heartbeat every 1 second
    monkeypatch.setenv("SSE_HEARTBEAT_SECONDS", "1")
    from app.config import get_settings
    get_settings.cache_clear()

    sid = "TESTSESSION"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=5.0) as client:
        async with client.stream("GET", f"/quizzes/{sid}/stream") as r:  # type: ignore[attr-defined]
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            # Read chunks until we find a heartbeat
            found = False
            async for chunk in r.aiter_bytes():
                if b"event: heartbeat" in chunk:
                    found = True
                    break
            assert found, "Expected to observe at least one heartbeat frame"