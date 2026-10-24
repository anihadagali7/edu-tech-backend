import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import models_study
from app.features.learning_content import service
from app.features.learning_content.schemas import GenerateMaterialRequest
from app.utils.errors import AppError


@pytest.mark.asyncio
async def test_enqueue_learning_material_job_persists_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "ENABLE_LEARNING_MATERIALS", True)

    session = SimpleNamespace(
        add=MagicMock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    material = models_study.LearningMaterial(
        id=uuid.uuid4(),
        topic_id=uuid.uuid4(),
        title="Draft",
        status="draft",
    )

    repo = SimpleNamespace(
        _session=session,
        create_material=AsyncMock(return_value=material),
    )

    job_id = await service.enqueue_learning_material_job(
        repository=repo,
        payload=GenerateMaterialRequest(topic_slug="algebra-basics"),
        requested_by=str(uuid.uuid4()),
    )

    assert isinstance(job_id, str)
    session.add.assert_called()  # job persisted
    repo.create_material.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_apply_material_artifact_updates_sections_and_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "ENABLE_LEARNING_MATERIALS", True)

    session = SimpleNamespace(
        execute=AsyncMock(),
        add=MagicMock(),
        flush=AsyncMock(),
    )

    material = models_study.LearningMaterial(
        id=uuid.uuid4(),
        topic_id=uuid.uuid4(),
        title="Draft",
        status="draft",
    )
    material.topic = SimpleNamespace(slug="algebra-basics")
    material.sections = []

    repo = SimpleNamespace(_session=session)

    artifact = service.MaterialArtifact(
        topic_slug="algebra-basics",
        title="Final Title",
        summary="Summary",
        content_markdown="# Heading\n\nBody",
        sections=[service.MaterialSectionArtifact(title="Intro", content_markdown="Body", order=0)],
        metadata={"difficulty": "beginner"},
    )

    monkeypatch.setattr(service, "_write_artifact_to_disk", lambda *_args, **_kwargs: "file://artifact")

    calls: list[tuple] = []

    class CaptureIndexer:
        async def index_material(self, **kwargs):  # type: ignore[override]
            calls.append(kwargs)

    service.set_material_indexer_for_testing(CaptureIndexer())
    try:
        updated = await service.apply_material_artifact(
            repository=repo,
            material_id=str(material.id),
            artifact=artifact,
            material=material,
        )
    finally:
        service.set_material_indexer_for_testing(None)

    assert updated.status == "published"
    assert updated.title == "Final Title"
    session.execute.assert_awaited_once()
    assert session.add.call_count == len(artifact.sections)
    assert calls and calls[0]["material_id"] == str(material.id)


@pytest.mark.asyncio
async def test_material_to_response_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "ENABLE_LEARNING_MATERIALS", True)
    loader = AsyncMock(side_effect=AppError("missing", code="x", status=404))
    monkeypatch.setattr(service, "_load_material_entity", loader)

    repo = SimpleNamespace(_session=None)
    with pytest.raises(AppError):
        await service.material_to_response(repo, "deadbeef-dead-beef-dead-beefdeadbeef")


@pytest.mark.asyncio
async def test_material_to_response_serializes_entity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "ENABLE_LEARNING_MATERIALS", True)

    material = models_study.LearningMaterial(
        id=uuid.uuid4(),
        topic_id=uuid.uuid4(),
        title="Ready",
        status="published",
    )
    material.topic = SimpleNamespace(slug="algebra-basics")
    material.sections = []

    loader = AsyncMock(return_value=material)
    monkeypatch.setattr(service, "_load_material_entity", loader)

    repo = SimpleNamespace(_session=None)
    result = await service.material_to_response(repo, str(material.id))
    assert result.topic_slug == "algebra-basics"
    assert result.title == "Ready"


@pytest.mark.asyncio
async def test_get_and_list_materials_delegate_to_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "ENABLE_LEARNING_MATERIALS", True)

    material = models_study.LearningMaterial(
        id=uuid.uuid4(),
        topic_id=uuid.uuid4(),
        title="Algebra",
        status="published",
    )
    material.topic = SimpleNamespace(slug="algebra-basics")
    material.sections = []

    repo = SimpleNamespace(
        get_material_by_topic=AsyncMock(return_value=material),
        list_materials=AsyncMock(return_value=[material]),
    )

    single = await service.get_material_for_topic(repo, "algebra-basics", user_id="user-1")
    assert single.title == "Algebra"

    listing = await service.list_materials_for_user(repo, user_id="user-1", limit=5, offset=0)
    assert len(listing) == 1
    assert listing[0].topic_slug == "algebra-basics"