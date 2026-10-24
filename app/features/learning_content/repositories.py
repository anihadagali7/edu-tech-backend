"""Repositories for learning material persistence and retrieval."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import models_study
from app.db.models import Topic
from app.features.learning_content.schemas import GenerateMaterialRequest
from app.utils.errors import AppError, LC404_MATERIAL_NOT_FOUND, TOP404_NOT_FOUND


class LearningContentRepository:
    """Repository encapsulating database operations for learning materials and their sections across admin and learner flows.

    TODO:
    1. Inject feature flags or RBAC helpers if repository needs to enforce access control at the data layer.
    2. Share serialization helpers with service layer to avoid duplicate mapping logic.
    3. Align transaction lifecycle with other repositories (context manager or explicit commit model).

    Acceptance:
    - Supports both request-scoped and background job usage without mutation of global state.
    - Exposes async-friendly CRUD APIs consumed by routers and worker handlers.
    - Remains easily mockable for unit tests by abstracting SQLAlchemy specifics when necessary.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Store an async session for executing learning content queries within a controlled transaction scope.

        TODO:
        1. Accept optional logger or clock dependencies if needed for auditing.
        2. Ensure the session observes the same RLS policies as other repositories by including tenant columns.
        3. Document whether the repository is per-request or shared across tasks.

        Acceptance:
        - Constructor should not execute I/O and simply retain references.
        - Compatible with dependency injection patterns used in the application.
        - Supports unit testing via async session mocks or fakes.
        """
        self._session = session

    async def create_material(
        self,
        payload: GenerateMaterialRequest,
        requested_by: str,
        job_id: str,
    ) -> models_study.LearningMaterial:
        """Insert a draft learning material record and associated sections in preparation for LLM-generated content.

        TODO:
        1. Begin a transaction and insert a LearningMaterial row containing status, topic, and requester metadata.
        2. Optionally create placeholder LearningSection rows based on payload structure.
        3. Persist worker job references for downstream tracking and idempotency.
        4. Commit the transaction and return the ORM entity with primary key populated.

        Acceptance:
        - Returns a LearningMaterial instance tied to the correct tenant/user.
        - Rolls back changes if any insert fails to maintain integrity.
        - Captures provenance data required by analytics and auditing.
        """
        topic_stmt = select(Topic).where(
            Topic.slug == payload.topic_slug,
            Topic.is_deleted.is_(False),
        )
        topic_result = await self._session.execute(topic_stmt)
        topic = topic_result.scalar_one_or_none()
        if topic is None:
            raise AppError("topic not found", code=TOP404_NOT_FOUND, status=404)

        material = models_study.LearningMaterial(
            topic_id=topic.id,
            title=self._derive_title(payload.topic_slug),
            summary=None,
            content_markdown=None,
            status="draft",
            requested_by=self._optional_uuid(requested_by),
            job_id=self._optional_uuid(job_id),
        )

        self._session.add(material)
        await self._session.flush()
        return material

    async def get_material_by_topic(
        self,
        topic_slug: str,
        user_id: str,
    ) -> models_study.LearningMaterial:
        """Retrieve the most recent approved learning material for a topic visible to the requesting user.

        TODO:
        1. Query LearningMaterial rows filtered by topic slug, publication status, and tenant access rules.
        2. Join related LearningSection rows to avoid N+1 retrieval when returning content.
        3. Handle absence of content by raising a domain-specific not-found error.
        4. Optionally implement soft-deletion filters to hide archived materials.

        Acceptance:
        - Returns a single LearningMaterial ORM instance with sections eagerly loaded.
        - Respects RLS policies, ensuring users cannot access other tenants' content.
        - Performs efficiently with proper indexing on topic slug and status columns.
        """
        requester_uuid = self._optional_uuid(user_id)

        stmt = select(models_study.LearningMaterial).options(selectinload(models_study.LearningMaterial.sections)).join(
            Topic, Topic.id == models_study.LearningMaterial.topic_id
        )

        stmt = stmt.where(
            Topic.slug == topic_slug,
            Topic.is_deleted.is_(False),
        )

        topic_visibility = [Topic.is_published.is_(True)]
        if requester_uuid is not None:
            topic_visibility.append(models_study.LearningMaterial.requested_by == requester_uuid)
        stmt = stmt.where(or_(*topic_visibility))

        material_visibility = [models_study.LearningMaterial.status == "published"]
        if requester_uuid is not None:
            material_visibility.append(models_study.LearningMaterial.requested_by == requester_uuid)
        stmt = stmt.where(or_(*material_visibility))

        stmt = stmt.order_by(desc(models_study.LearningMaterial.created_at)).limit(1)
        result = await self._session.execute(stmt)
        material = result.scalar_one_or_none()
        if material is None:
            raise AppError("learning material not found", code=LC404_MATERIAL_NOT_FOUND, status=404)
        return material

    async def list_materials(
        self,
        user_id: str,
        limit: int,
        offset: int,
    ) -> Sequence[models_study.LearningMaterial]:
        """List learning materials accessible to the user with pagination support for dashboard views.

        TODO:
        1. Build a query filtering by tenant/user and ordering by updated_at descending.
        2. Apply limit/offset for pagination, retrieving sections lazily or eagerly as required.
        3. Return ORM entities ready for serialization or transformation.
        4. Collect total counts when needed for pagination metadata (optional future enhancement).

        Acceptance:
        - Returns a sequence of LearningMaterial entities within the requested window.
        - Maintains stable ordering to avoid duplicate entries across pages.
        - Efficient for large datasets due to appropriate indexing and query planning.
        """
        if limit <= 0:
            return []

        requester_uuid = self._optional_uuid(user_id)

        stmt = select(models_study.LearningMaterial).options(selectinload(models_study.LearningMaterial.sections)).join(
            Topic, Topic.id == models_study.LearningMaterial.topic_id
        )

        stmt = stmt.where(Topic.is_deleted.is_(False))

        topic_visibility = [Topic.is_published.is_(True)]
        if requester_uuid is not None:
            topic_visibility.append(models_study.LearningMaterial.requested_by == requester_uuid)
        stmt = stmt.where(or_(*topic_visibility))

        material_visibility = [models_study.LearningMaterial.status == "published"]
        if requester_uuid is not None:
            material_visibility.append(models_study.LearningMaterial.requested_by == requester_uuid)
        stmt = stmt.where(or_(*material_visibility))

        stmt = stmt.order_by(desc(models_study.LearningMaterial.updated_at)).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    @staticmethod
    def _optional_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
        if value is None or value == "":
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):  # pragma: no cover - defensive guard
            return None

    @staticmethod
    def _derive_title(slug: str) -> str:
        cleaned = slug.replace("_", " ").replace("-", " ").strip()
        return cleaned.title() if cleaned else slug
