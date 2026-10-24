"""Service layer for generating, validating, and persisting learning materials via LLM jobs."""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import models_study
from app.db.models import Event, LLMJob
from app.features.learning_content import ENABLE_LEARNING_MATERIALS
from app.features.learning_content.repositories import LearningContentRepository
from app.features.learning_content.schemas import GenerateMaterialRequest, LearningMaterialOut, LearningSectionOut
from app.features.llm.job_types import LLMJobType
from app.utils.errors import AppError, LC404_MATERIAL_NOT_FOUND

logger = logging.getLogger("learning_content.service")
_ARTIFACT_DIR = Path(os.getenv("LEARNING_MATERIAL_ARTIFACT_DIR", ".artifacts/learning-materials"))


@dataclass
class MaterialSectionArtifact:
    title: str
    content_markdown: str
    order: int = 0


@dataclass
class MaterialArtifact:
    topic_slug: str
    title: str
    summary: str
    content_markdown: str
    sections: list[MaterialSectionArtifact] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class MaterialIndexer(Protocol):
    async def index_material(
        self,
        *,
        material_id: str,
        topic_id: str | None,
        sections: Sequence[MaterialSectionArtifact],
        metadata: dict[str, Any],
    ) -> None:  # pragma: no cover - interface definition
        ...


class _NoopMaterialIndexer(MaterialIndexer):
    async def index_material(
        self,
        *,
        material_id: str,
        topic_id: str | None,
        sections: Sequence[MaterialSectionArtifact],
        metadata: dict[str, Any],
    ) -> None:
        return None


_MATERIAL_INDEXER: MaterialIndexer = _NoopMaterialIndexer()


def set_material_indexer_for_testing(indexer: MaterialIndexer | None) -> None:  # pragma: no cover - test hook
    global _MATERIAL_INDEXER
    _MATERIAL_INDEXER = indexer or _NoopMaterialIndexer()


def _ensure_feature_enabled() -> None:
    if not ENABLE_LEARNING_MATERIALS:
        raise RuntimeError("Learning materials feature is disabled")


def _repository_session(repository: LearningContentRepository) -> AsyncSession:
    session = getattr(repository, "_session", None)
    if session is None:
        raise RuntimeError("LearningContentRepository is missing bound session")
    return session


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):  # pragma: no cover - defensive guard
        return None


async def enqueue_learning_material_job(
    repository: LearningContentRepository,
    payload: GenerateMaterialRequest,
    requested_by: str,
) -> str:
    """Schedule a learning material generation job and persist a draft record."""

    _ensure_feature_enabled()
    session = _repository_session(repository)

    job = LLMJob(
        job_type=LLMJobType.LEARNING_MATERIAL_GENERATION.value,
        status="queued",
        topic_slug=payload.topic_slug,
        topic_name=payload.title or payload.topic_slug.replace("-", " ").title(),
        params={"request": payload.model_dump(exclude_none=True)},
        requested_by=_coerce_uuid(requested_by),
    )
    session.add(job)

    try:
        await session.flush()
        material = await repository.create_material(payload, requested_by=requested_by, job_id=str(job.id))
        job.params["material_id"] = str(getattr(material, "id"))
        # Mark job as modified to ensure params dict change is persisted
        from sqlalchemy.orm import attributes
        attributes.flag_modified(job, "params")
        await session.flush()
        await session.commit()
        logger.info(
            "learning_material_job_enqueued",
            extra={"job_id": str(job.id), "topic_slug": payload.topic_slug},
        )
        return str(job.id)
    except Exception:  # pragma: no cover - transaction guard
        await session.rollback()
        logger.exception("learning_material_job_enqueue_failed", extra={"topic_slug": payload.topic_slug})
        raise


async def material_to_response(
    repository: LearningContentRepository,
    material_id: str,
) -> LearningMaterialOut:
    """Load a learning material by ID and convert it to the outward-facing schema."""

    _ensure_feature_enabled()
    material = await _load_material_entity(repository, material_id)
    return _material_to_schema(material)


async def get_material_for_topic(
    repository: LearningContentRepository,
    topic_slug: str,
    user_id: str,
) -> LearningMaterialOut:
    """Fetch and serialize the most recent published material for a topic."""

    _ensure_feature_enabled()
    material = await repository.get_material_by_topic(topic_slug, user_id)
    return _material_to_schema(material)


async def list_materials_for_user(
    repository: LearningContentRepository,
    user_id: str,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[LearningMaterialOut]:
    """Return a paginated list of accessible materials for dashboards."""

    _ensure_feature_enabled()
    rows = await repository.list_materials(user_id=user_id, limit=limit, offset=offset)
    return [_material_to_schema(row) for row in rows]


async def apply_material_artifact(
    repository: LearningContentRepository,
    material_id: str,
    artifact: MaterialArtifact,
    *,
    publish: bool = True,
    material: models_study.LearningMaterial | None = None,
) -> models_study.LearningMaterial:
    """Persist generated artifact content, sections, and index metadata."""

    _ensure_feature_enabled()
    session = _repository_session(repository)
    entity = material or await _load_material_entity(repository, material_id, eager_load=True)

    entity.title = artifact.title or entity.title
    entity.summary = artifact.summary or entity.summary
    entity.content_markdown = artifact.content_markdown or _sections_to_markdown(artifact.sections)
    if publish:
        entity.status = "published"

    await session.execute(
        sa.delete(models_study.LearningSection).where(models_study.LearningSection.material_id == entity.id)
    )

    for section in artifact.sections:
        section_entity = models_study.LearningSection(
            material_id=entity.id,
            title=section.title,
            content_markdown=section.content_markdown,
            position=section.order,
        )
        session.add(section_entity)

    artifact_uri = _write_artifact_to_disk(material_id, artifact)
    if artifact_uri:
        entity.artifact_uri = artifact_uri

    await session.flush()

    topic_slug = getattr(getattr(entity, "topic", None), "slug", artifact.topic_slug)
    await _index_material(
        material_id=str(entity.id),
        topic_id=str(entity.topic_id) if entity.topic_id else None,
        sections=artifact.sections,
        metadata={"topic_slug": topic_slug, **artifact.metadata},
    )

    return entity


async def record_material_event(
    session: AsyncSession,
    *,
    material_id: str,
    job_id: str,
    event_type: str = "LEARNING_MATERIAL_READY",
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit a structured event when material generation milestones complete."""

    event = Event(
        event_type=event_type,
        payload={"material_id": material_id, "job_id": job_id, **(payload or {})},
        session_id=None,
        user_id=None,
    )
    session.add(event)
    await session.flush()


async def _load_material_entity(
    repository: LearningContentRepository,
    material_id: str,
    *,
    eager_load: bool = True,
) -> models_study.LearningMaterial:
    session = _repository_session(repository)
    try:
        material_uuid = material_id if isinstance(material_id, uuid.UUID) else uuid.UUID(str(material_id))
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive guard
        raise AppError("learning material not found", code=LC404_MATERIAL_NOT_FOUND, status=404) from exc

    stmt = sa.select(models_study.LearningMaterial).where(models_study.LearningMaterial.id == material_uuid)
    if eager_load:
        stmt = stmt.options(
            selectinload(models_study.LearningMaterial.sections),
            selectinload(models_study.LearningMaterial.topic),
        )
    result = await session.execute(stmt)
    material = result.scalar_one_or_none()
    if material is None:
        raise AppError("learning material not found", code=LC404_MATERIAL_NOT_FOUND, status=404)
    return material


def _material_to_schema(material: models_study.LearningMaterial) -> LearningMaterialOut:
    topic_slug = getattr(getattr(material, "topic", None), "slug", None)
    if not topic_slug:
        topic_slug = (material.title or "material").strip().lower().replace(" ", "-")

    sections = sorted(list(getattr(material, "sections", []) or []), key=lambda s: getattr(s, "position", 0))
    section_out = [
        LearningSectionOut(
            id=str(section.id),
            title=section.title,
            content_markdown=section.content_markdown or "",
            order=getattr(section, "position", index),
        )
        for index, section in enumerate(sections)
    ]

    return LearningMaterialOut(
        id=str(material.id),
        topic_slug=topic_slug,
        title=material.title,
        summary=material.summary,
        content_markdown=material.content_markdown,
        status=material.status,
        created_at=getattr(material, "created_at", None),
        updated_at=getattr(material, "updated_at", None),
        sections=section_out,
    )


def _sections_to_markdown(sections: Sequence[MaterialSectionArtifact]) -> str:
    if not sections:
        return ""
    parts = []
    for section in sections:
        header = f"## {section.title}\n\n" if section.title else ""
        parts.append(f"{header}{section.content_markdown}".strip())
    return "\n\n".join(part for part in parts if part)


def _write_artifact_to_disk(material_id: str, artifact: MaterialArtifact) -> str | None:
    try:
        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        path = _ARTIFACT_DIR / f"{material_id}.json"
        path.write_text(
            json.dumps(
                {
                    "topic_slug": artifact.topic_slug,
                    "title": artifact.title,
                    "summary": artifact.summary,
                    "content_markdown": artifact.content_markdown,
                    "sections": [
                        {
                            "title": section.title,
                            "content_markdown": section.content_markdown,
                            "order": section.order,
                        }
                        for section in artifact.sections
                    ],
                    "metadata": artifact.metadata,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(path)
    except Exception:  # pragma: no cover - best effort persistence
        logger.warning("learning_material_artifact_write_failed", exc_info=True)
        return None


async def _index_material(
    *,
    material_id: str,
    topic_id: str | None,
    sections: Sequence[MaterialSectionArtifact],
    metadata: dict[str, Any],
) -> None:
    try:
        await _MATERIAL_INDEXER.index_material(
            material_id=material_id,
            topic_id=topic_id,
            sections=sections,
            metadata=metadata,
        )
    except Exception:  # pragma: no cover - analytics only
        logger.warning("learning_material_index_failed", extra={"material_id": material_id}, exc_info=True)
