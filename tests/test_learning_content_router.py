"""Router smoke tests for learning material endpoints."""

from __future__ import annotations

from typing import AsyncGenerator
import uuid

import pytest
import pytest_asyncio
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from app.api import routes as api_routes
from app.api import routes_study_buddy
from app.auth.middleware import clerk_auth_dependency
from app.features.learning_content import router as learning_router
from app.features.learning_content.schemas import LearningMaterialOut, LearningSectionOut
from app.main import app


@pytest_asyncio.fixture
async def client_fixture(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    async def _admin_user(request: Request) -> dict[str, str]:
        principal = {"id": str(uuid.uuid4()), "role": "admin"}
        request.state.user = principal
        return principal

    monkeypatch.setattr("app.features.learning_content.ENABLE_LEARNING_MATERIALS", True, raising=False)
    monkeypatch.setattr(routes_study_buddy, "ENABLE_LEARNING_MATERIALS", True, raising=False)
    monkeypatch.setattr(learning_router, "ENABLE_LEARNING_MATERIALS", True, raising=False)
    routes_study_buddy.include_study_buddy_routes(api_routes.api)
    app.dependency_overrides[clerk_auth_dependency] = _admin_user
    if not any(getattr(route, "path", "") == "/admin/learning-materials/generate" for route in app.router.routes):
        app.include_router(learning_router.router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.pop(clerk_auth_dependency, None)


@pytest.mark.asyncio
async def test_generate_material_admin_only(monkeypatch: pytest.MonkeyPatch, client_fixture: AsyncClient) -> None:
    async def _enqueue(*_args, **_kwargs):
        return "job-123"

    async def _trigger(job_id: str) -> None:
        return None

    class StubRepo:
        def __init__(self, session):  # type: ignore[unused-argument]
            self._session = session

    monkeypatch.setattr(learning_router.service, "enqueue_learning_material_job", _enqueue)
    monkeypatch.setattr(learning_router, "LearningContentRepository", StubRepo)
    monkeypatch.setattr(learning_router, "trigger_worker_async", _trigger)

    response = await client_fixture.post(
        "/admin/learning-materials/generate",
        json={"topic_slug": "algebra-basics"},
    )

    assert response.status_code == 202
    assert response.json()["job_id"] == "job-123"


@pytest.mark.asyncio
async def test_get_learning_material_returns_payload(monkeypatch: pytest.MonkeyPatch, client_fixture: AsyncClient) -> None:
    material = LearningMaterialOut(
        id="mat-1",
        topic_slug="algebra-basics",
        title="Algebra",
        summary="Summary",
        status="published",
        sections=[
            LearningSectionOut(id="sec-1", title="Intro", content_markdown="# Intro", order=0)
        ],
    )

    async def _get(*_args, **_kwargs):
        return material

    class StubRepo:
        def __init__(self, session):  # type: ignore[unused-argument]
            self._session = session

    monkeypatch.setattr(learning_router.service, "get_material_for_topic", _get)
    monkeypatch.setattr(learning_router, "LearningContentRepository", StubRepo)

    response = await client_fixture.get("/learning-materials/algebra-basics")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Algebra"
    assert body["sections"][0]["title"] == "Intro"


@pytest.mark.asyncio
async def test_list_learning_materials_returns_collection(monkeypatch: pytest.MonkeyPatch, client_fixture: AsyncClient) -> None:
    payload = LearningMaterialOut(
        id="mat-1",
        topic_slug="geometry",
        title="Geometry",
        summary="Summary",
        status="published",
        sections=[],
    )

    async def _list(*_args, **_kwargs):
        return [payload]

    class StubRepo:
        def __init__(self, session):  # type: ignore[unused-argument]
            self._session = session

    monkeypatch.setattr(learning_router.service, "list_materials_for_user", _list)
    monkeypatch.setattr(learning_router, "LearningContentRepository", StubRepo)

    response = await client_fixture.get("/learning-materials")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["topic_slug"] == "geometry"
