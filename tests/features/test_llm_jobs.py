"""Tests for LLM jobs endpoint visibility (Module 3)."""

from __future__ import annotations

import types
from typing import Any, Optional
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.jwt import generate_token
from app.main import app
from app.utils.errors import LLM404_JOB_NOT_FOUND


class _Job:
    def __init__(self, id: str, requested_by: Optional[str]) -> None:
        self.id = UUID(id)
        self.status = "queued"
        self.topic_slug = "algebra"
        self.created_count = None
        self.error = None
        self.requested_by = UUID(requested_by) if requested_by else None


class _FakeResult:
    def __init__(self, job: Optional[_Job]) -> None:
        self._job = job

    def scalar_one_or_none(self) -> Optional[_Job]:
        return self._job


class _FakeSession:
    def __init__(self, job: Optional[_Job]) -> None:
        self._job = job

    async def execute(self, _stmt) -> _FakeResult:
        # ignore the statement specifics; return our configured job
        return _FakeResult(self._job)


@pytest.mark.asyncio
async def test_jobs_requires_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/llm/jobs/00000000-0000-0000-0000-000000000001")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_owner_sees_own_job(monkeypatch: pytest.MonkeyPatch) -> None:
    # Prepare a job owned by the requester
    owner_id = "00000000-0000-0000-0000-0000000000aa"
    job = _Job("00000000-0000-0000-0000-000000000001", requested_by=owner_id)

    import app.features.llm.jobs as J
    monkeypatch.setattr(J, "get_session", lambda: _FakeSession(job))  # dependency override

    token = generate_token(subject=owner_id, role="user")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        r = await client.get("/llm/jobs/00000000-0000-0000-0000-000000000001")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["status"] == "queued"
        assert body["data"]["topic_slug"] == "algebra"


@pytest.mark.asyncio
async def test_non_owner_gets_404(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _Job("00000000-0000-0000-0000-000000000002", requested_by="00000000-0000-0000-0000-0000000000ee")

    import app.features.llm.jobs as J
    monkeypatch.setattr(J, "get_session", lambda: _FakeSession(job))

    token = generate_token(subject="00000000-0000-0000-0000-0000000000ff", role="user")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        r = await client.get("/llm/jobs/00000000-0000-0000-0000-000000000002")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == LLM404_JOB_NOT_FOUND


@pytest.mark.asyncio
async def test_admin_sees_any_job(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _Job("00000000-0000-0000-0000-000000000003", requested_by="00000000-0000-0000-0000-0000000000ee")

    import app.features.llm.jobs as J
    monkeypatch.setattr(J, "get_session", lambda: _FakeSession(job))

    token = generate_token(subject="00000000-0000-0000-0000-0000000000ab", role="admin")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        r = await client.get("/llm/jobs/00000000-0000-0000-0000-000000000003")
        assert r.status_code == 200
        assert r.json()["data"]["id"] == "00000000-0000-0000-0000-000000000003"
