"""Quizzes endpoints should be stubbed (501) in skeleton.

Maps to Section 6.2 of the design: Endpoint scaffolds without business logic.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_quizzes_start_stub() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/quizzes/start", json={"topic_id": None})
        assert r.status_code == 501


@pytest.mark.asyncio
async def test_quizzes_summary_stub() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/quizzes/abc123/summary")
        assert r.status_code == 501


@pytest.mark.asyncio
async def test_quizzes_start_requires_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/quizzes/start", json={"topic_name": "Any"})
        assert r.status_code == 401
