# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""Tests for Study Buddy router and SSE streaming endpoints."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api import routes as api_routes
from app.api import routes_study_buddy
from app.auth.middleware import clerk_auth_dependency
from app.features.study_buddy import service as study_service
from app.features.study_buddy.router import router as study_router
from app.features.study_buddy.sse import router as study_sse_router
from app.features.study_buddy.schemas import ContextSnapshot, StartStudySessionRequest, StudyMessageRequest, StudyMode
from app.main import app


def _enable_study_buddy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.features.study_buddy.ENABLE_STUDY_BUDDY", True, raising=False)
    monkeypatch.setattr("app.features.study_buddy.router.ENABLE_STUDY_BUDDY", True, raising=False)
    monkeypatch.setattr("app.features.study_buddy.sse.ENABLE_STUDY_BUDDY", True, raising=False)
    monkeypatch.setattr("app.features.study_buddy.service.ENABLE_STUDY_BUDDY", True, raising=False)
    monkeypatch.setattr("app.api.routes_study_buddy.ENABLE_STUDY_BUDDY", True, raising=False)

    if not any(getattr(route, "path", "") == "/study-buddy/sessions" for route in app.router.routes):
        app.include_router(study_router)
    if not any(getattr(route, "path", "") == "/sse/study-buddy/{session_id}" for route in app.router.routes):
        app.include_router(study_sse_router)


def _disable_study_buddy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.features.study_buddy.ENABLE_STUDY_BUDDY", False, raising=False)
    monkeypatch.setattr("app.features.study_buddy.router.ENABLE_STUDY_BUDDY", False, raising=False)
    monkeypatch.setattr("app.features.study_buddy.sse.ENABLE_STUDY_BUDDY", False, raising=False)
    monkeypatch.setattr("app.features.study_buddy.service.ENABLE_STUDY_BUDDY", False, raising=False)
    monkeypatch.setattr("app.api.routes_study_buddy.ENABLE_STUDY_BUDDY", False, raising=False)


@pytest_asyncio.fixture
async def client_fixture(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    async def _fake_auth() -> dict[str, str]:
        return {"id": "user-123", "clerk_user_id": "user-123", "role": "user"}

    app.dependency_overrides[clerk_auth_dependency] = _fake_auth
    study_service.reset_state_for_testing()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.pop(clerk_auth_dependency, None)
    study_service.reset_state_for_testing()


@pytest.mark.asyncio
async def test_start_session_happy_path(monkeypatch: pytest.MonkeyPatch, client_fixture: AsyncClient) -> None:
    _enable_study_buddy(monkeypatch)
    routes_study_buddy.include_study_buddy_routes(api_routes.api)

    response = await client_fixture.post("/study-buddy/sessions", json={"mode": "reading"})
    assert response.status_code == 201

    body = response.json()
    assert body["session_id"]
    assert body["mode"] == "reading"
    assert body["hint"]["level"] == 0
    assert body["sse_url"].startswith("/sse/study-buddy/")
    assert body["sse_url"].split("/")[-1] == body["session_id"]


@pytest.mark.asyncio
async def test_post_message_requires_feature_flag(monkeypatch: pytest.MonkeyPatch, client_fixture: AsyncClient) -> None:
    _disable_study_buddy(monkeypatch)

    response = await client_fixture.post(
        "/study-buddy/sessions/fake-session/messages",
        json={"message": "Hello"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Study Buddy feature is disabled"


@pytest.mark.asyncio
async def test_study_buddy_sse_stream(monkeypatch: pytest.MonkeyPatch, client_fixture: AsyncClient) -> None:
    _enable_study_buddy(monkeypatch)
    routes_study_buddy.include_study_buddy_routes(api_routes.api)

    async def _fake_retrieve_documents(mode, context, last_error):  # type: ignore[unused-arg]
        docs = [
            {"title": "Doc One", "content": "Key idea about fractions."},
        ]
        context.retrieved_documents = docs
        context.retrieval_metadata = {"backend": "test"}
        return docs

    async def _fake_llm_responder(mode, payload):  # type: ignore[unused-arg]
        return "Here is a deterministic tutor reply referencing Doc One."

    monkeypatch.setattr(study_service, "retrieve_documents", _fake_retrieve_documents)
    study_service.set_llm_responder_for_testing(_fake_llm_responder)

    # Create session and enqueue message
    start_response = await client_fixture.post("/study-buddy/sessions", json={"mode": "quiz"})
    session_id = start_response.json()["session_id"]

    message_response = await client_fixture.post(
        f"/study-buddy/sessions/{session_id}/messages",
        json={"message": "Explain the concept"},
    )
    assert message_response.status_code == 202
    sse_url = message_response.json()["sse_url"]

    try:
        async with client_fixture.stream("GET", sse_url, headers={"Accept": "text/event-stream"}) as stream_response:
            events: list[tuple[str, dict[str, Any]]] = []
            current_event: str | None = None

            async for line in stream_response.aiter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and current_event:
                    payload_text = line.split(":", 1)[1].strip()
                    try:
                        payload = json.loads(payload_text)
                    except json.JSONDecodeError:
                        payload = {"raw": payload_text}
                    events.append((current_event, payload))
                    if current_event == "done":
                        break
    finally:
        study_service.set_llm_responder_for_testing(None)

    event_types = [event for event, _ in events]
    assert "hint_meta" in event_types
    assert "token" in event_types
    assert event_types[-1] == "done"

    hint_payload = next(payload for event, payload in events if event == "hint_meta")
    assert hint_payload["sources"] == ["Doc One"]


@pytest.mark.asyncio
async def test_study_buddy_quiz_mode_blocks_leak(monkeypatch: pytest.MonkeyPatch, client_fixture: AsyncClient) -> None:
    """E2E flow ensures quiz hints stream without leaking final answers."""

    _enable_study_buddy(monkeypatch)
    routes_study_buddy.include_study_buddy_routes(api_routes.api)

    async def _fake_retrieve_documents(mode, context, last_error):  # type: ignore[unused-arg]
        docs = [
            {"title": "Doc Two", "content": "Reminder about the Pythagorean theorem."},
        ]
        context.retrieved_documents = docs
        context.retrieval_metadata = {"backend": "test"}
        return docs

    async def _leaky_responder(mode, payload):  # type: ignore[unused-arg]
        return "The answer is 42. Option C is correct."

    monkeypatch.setattr(study_service, "retrieve_documents", _fake_retrieve_documents)
    study_service.set_llm_responder_for_testing(_leaky_responder)

    start_response = await client_fixture.post("/study-buddy/sessions", json={"mode": "quiz"})
    session_id = start_response.json()["session_id"]

    message_response = await client_fixture.post(
        f"/study-buddy/sessions/{session_id}/messages",
        json={"message": "What's the hypotenuse?", "mode": "quiz"},
    )
    assert message_response.status_code == 202
    sse_url = message_response.json()["sse_url"]

    try:
        async with client_fixture.stream("GET", sse_url, headers={"Accept": "text/event-stream"}) as stream_response:
            events: list[tuple[str, Any]] = []
            current_event: str | None = None
            async for line in stream_response.aiter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and current_event:
                    payload_text = line.split(":", 1)[1].strip()
                    try:
                        payload = json.loads(payload_text)
                    except json.JSONDecodeError:
                        payload = {"raw": payload_text}
                    events.append((current_event, payload))
                    if current_event == "done":
                        break
    finally:
        study_service.set_llm_responder_for_testing(None)

    assert any(event == "hint_meta" for event, _ in events)
    assert events[-1][0] == "done"

    streamed_text = "".join(payload["text"] for event, payload in events if event == "token")
    assert "answer is" not in streamed_text.lower()
    assert "[hint redacted]" in streamed_text or "[choice hidden]" in streamed_text
    assert "hint" in streamed_text.lower() or "focus" in streamed_text.lower()
