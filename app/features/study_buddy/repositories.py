"""Database repositories for Study Buddy sessions, messages, history, and analytics."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models_study
from app.db.models import Session  # Import Session model to look up by session_uid
from app.features.study_buddy.schemas import ContextSnapshot, StudyMessageResponse
from app.utils.errors import AppError, STB404_SESSION_NOT_FOUND, STB422_ANALYTICS_EVENT_TYPE_REQUIRED

_ = StudyMessageResponse


class StudyBuddyRepository:
    """Repository coordinating persistence for Study Buddy sessions, messages, question history, and analytics records.

    TODO:
    1. Inject AsyncSession or unit-of-work dependencies via constructor for transactional control.
    2. Provide helper methods for mapping ORM entities into Pydantic response models.
    3. Enforce tenant scoping by filtering queries with Clerk user identifiers.

    Acceptance:
    - All CRUD operations share a consistent transaction boundary strategy.
    - Unit tests can mock this class to avoid touching the database.
    - Repository remains agnostic of higher-level business rules.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Store the SQLAlchemy session for later transactional operations across repository methods.

        TODO:
        1. Validate that the session is tied to the correct engine/transaction scope.
        2. Consider accepting additional dependencies (feature flags, clock) for audit logging.
        3. Document lifecycle expectations (per-request vs. background job usage).

        Acceptance:
        - Constructor performs no database work and simply stores references.
        - Works with dependency injection frameworks used by the application today.
        - Supports context-managed lifespan when paired with FastAPI dependencies.
        """
        self._session = session

    async def create_study_session(
        self,
        user_id: str,
        payload: ContextSnapshot,
        mode: str,
    ) -> models_study.StudySession:
        """Create a new study session row, initializing context metadata and default hint counters with transactional safety.

        TODO:
        1. Begin a database transaction and insert a StudySession row keyed by the user's Clerk ID.
        2. Persist the serialized context snapshot and any derived metadata (e.g., default hint level).
        3. Emit domain events or audit logs via existing event publisher utilities once the transaction commits.
        4. Handle unique constraint violations gracefully, possibly by returning the existing open session.

        Acceptance:
        - Returns the newly created StudySession ORM instance with primary key populated.
        - Enforces RLS policies by including tenant-specific columns required by Supabase.
        - Rolls back the transaction on errors without leaving partial rows.
        """
        context_dict = payload.model_dump(exclude_none=True)

        session_kwargs: dict[str, Any] = {
            "user_clerk_id": user_id,
            "mode": mode,
        }

        topic_uuid = self._optional_uuid(context_dict.get("topic_id"))
        material_uuid = self._optional_uuid(context_dict.get("learning_material_id"))
        
        # Handle session_id: it should be a session_uid (string) that we store directly
        # linked_quiz_session_id now stores session_uid (TEXT) directly, not UUID id
        session_id_value = context_dict.get("session_id") or context_dict.get("quiz_id")
        quiz_session_uid = None
        if session_id_value:
            # linked_quiz_session_id now stores session_uid directly (TEXT)
            # Normalize the session_uid by removing hyphens for consistency
            quiz_session_uid = str(session_id_value).replace("-", "")
            # Optionally verify the session_uid exists in the database
            stmt = select(Session).where(Session.session_uid == quiz_session_uid)
            result = await self._session.execute(stmt)
            session_row = result.scalar_one_or_none()
            if session_row is None:
                # If the session_uid doesn't exist, set to None to avoid foreign key violations
                quiz_session_uid = None

        if topic_uuid is not None:
            session_kwargs["topic_id"] = topic_uuid
        if material_uuid is not None:
            session_kwargs["material_id"] = material_uuid
        if quiz_session_uid is not None:
            session_kwargs["linked_quiz_session_id"] = quiz_session_uid

        session_kwargs["context_snapshot"] = context_dict or None

        entity = models_study.StudySession(**session_kwargs)
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def get_session(self, user_id: str, session_id: str) -> models_study.StudySession:
        """Retrieve a study session ensuring the requesting user owns the record and applying optimistic locking if needed.

        TODO:
        1. Query the StudySession table with filters on session_id and user_id to satisfy RLS requirements.
        2. Eager-load recent messages and context snapshot for fast reads where appropriate.
        3. Raise a domain-specific exception when the session is not found to map to HTTP 404.
        4. Optionally update `last_accessed_at` to support analytics, deferring persistence until after commit.

        Acceptance:
        - Returns a StudySession ORM instance or raises a not-found error.
        - Plays nicely with SQLAlchemy async session semantics and does not block.
        - Works within an existing transaction without issuing implicit commits.
        """
        session_uuid = self._require_session_uuid(session_id)
        stmt = select(models_study.StudySession).where(
            models_study.StudySession.id == session_uuid,
            models_study.StudySession.user_clerk_id == user_id,
        )
        result = await self._session.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            raise AppError("session not found", code=STB404_SESSION_NOT_FOUND, status=404)
        return entity

    async def append_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        hint_level: int | None,
    ) -> models_study.StudyMessage:
        """Persist a message associated with the session, tagging role, hint level, and sequencing for chronological retrieval.

        TODO:
        1. Insert a StudyMessage row with proper foreign keys and ordering columns under an active transaction.
        2. Update session aggregates (last_message_at, hint counts) if necessary.
        3. Emit events for real-time streaming or analytics ingestion once the transaction commits.
        4. Guard against excessive message lengths in line with database constraints.

        Acceptance:
        - Returns the persisted StudyMessage instance with IDs populated.
        - Maintains chronological integrity via created_at or sequence fields.
        - Supports both user and tutor roles using a consistent schema.
        """
        session_entity = await self.get_session(user_id=user_id, session_id=session_id)

        message = models_study.StudyMessage(
            session_id=session_entity.id,
            role=role,
            content=content,
            hint_level=hint_level,
        )

        now = datetime.now(timezone.utc)
        session_entity.last_message_at = now
        session_entity.updated_at = now

        self._session.add(message)
        await self._session.flush()
        return message

    async def update_session_context(
        self,
        session_id: str,
        context: ContextSnapshot,
    ) -> models_study.StudySession:
        """Update the session's stored context snapshot when new materials or quiz references should override prior data.

        TODO:
        1. Serialize the ContextSnapshot into database-friendly columns or JSON fields.
        2. Execute an UPDATE statement scoped by session_id with optimistic concurrency checks.
        3. Return the refreshed StudySession entity for further processing.
        4. Handle race conditions by retrying or surfacing conflicts to upstream callers.

        Acceptance:
        - Ensures updated context persists and can be rehydrated into Pydantic models.
        - Respects RLS by including user/tenant filters in the update statement.
        - Leaves no partial updates if serialization fails.
        """
        session_entity = await self._load_session(session_id)
        if session_entity is None:
            raise AppError("session not found", code=STB404_SESSION_NOT_FOUND, status=404)

        context_payload = context.model_dump()
        session_entity.context_snapshot = {k: v for k, v in context_payload.items() if v is not None} or None

        session_entity.topic_id = self._optional_uuid(context_payload.get("topic_id"))
        session_entity.material_id = self._optional_uuid(context_payload.get("learning_material_id"))
        # linked_quiz_session_id now stores session_uid (TEXT) directly
        session_id_value = context_payload.get("session_id") or context_payload.get("quiz_id")
        if session_id_value:
            session_entity.linked_quiz_session_id = str(session_id_value).replace("-", "")
        else:
            session_entity.linked_quiz_session_id = None

        session_entity.updated_at = datetime.now(timezone.utc)

        await self._session.flush()
        return session_entity

    async def record_question_history(
        self,
        session_id: str,
        question_id: str,
        user_answer: str,
        outcome: str,
    ) -> models_study.QuestionHistory:
        """Log learner attempts against quiz questions to inform adaptive hinting and analytics dashboards.

        TODO:
        1. Insert a QuestionHistory row capturing attempts, outcomes, and timestamps.
        2. Link the record to both the study session and underlying quiz question foreign keys.
        3. Update aggregate fields (e.g., attempts count) on the session or analytics tables if necessary.
        4. Ensure rows respect Supabase RLS policies by including tenant columns.

        Acceptance:
        - Returns the persisted QuestionHistory ORM entity.
        - Supports idempotent writes when duplicate attempts occur in quick succession.
        - Provides clear errors when referenced quiz questions do not exist.
        """
        session_uuid = self._require_session_uuid(session_id)
        session_entity = await self._load_session(session_id)
        if session_entity is None:
            raise AppError("session not found", code=STB404_SESSION_NOT_FOUND, status=404)

        history = models_study.QuestionHistory(
            session_id=session_uuid,
            question_id=self._optional_uuid(question_id),
            user_answer=user_answer,
            outcome=outcome,
        )

        self._session.add(history)
        await self._session.flush()
        return history

    async def log_study_analytics(
        self,
        session_id: str,
        payload: dict[str, Any],
    ) -> models_study.StudyAnalytics:
        """Persist structured analytics events related to study sessions for downstream reporting and personalization.

        TODO:
        1. Validate payload schema before insert to avoid sparse or malformed records.
        2. Store the analytics in a JSONB column with indexes that support reporting queries.
        3. Tie analytics entries to the session and user for RLS compliance.
        4. Emit telemetry or events to notify other systems if analytics require near-real-time processing.

        Acceptance:
        - Returns the created StudyAnalytics ORM instance.
        - Handles large payloads within database limits without truncation.
        - Maintains referential integrity to the parent session.
        """
        session_uuid = self._require_session_uuid(session_id)
        session_entity = await self._load_session(session_id)
        if session_entity is None:
            raise AppError("session not found", code=STB404_SESSION_NOT_FOUND, status=404)

        payload_copy = dict(payload)
        event_type = payload_copy.get("event_type")
        if not isinstance(event_type, str) or not event_type:
            raise AppError("event_type required", code=STB422_ANALYTICS_EVENT_TYPE_REQUIRED, status=422)

        analytics = models_study.StudyAnalytics(
            session_id=session_uuid,
            event_type=event_type,
            payload=payload_copy,
        )

        self._session.add(analytics)
        await self._session.flush()
        return analytics

    async def recent_messages_for_session(
        self,
        session_id: str,
        limit: int,
    ) -> Sequence[models_study.StudyMessage]:
        """Fetch recent messages for rendering conversation history and summarization prompts with efficient pagination.

        TODO:
        1. Query StudyMessage rows ordered by created_at descending, limited by the provided parameter.
        2. Preload associated metadata (hint level, analytics) if required for prompt building.
        3. Return messages in chronological order expected by clients, reversing after fetch if necessary.
        4. Enforce tenant and session scope filters to honor RLS constraints.

        Acceptance:
        - Returns an ordered sequence of StudyMessage entities limited to the requested length.
        - Operates efficiently with proper indexing to support real-time streaming contexts.
        - Handles sessions with fewer messages than requested gracefully.
        """
        if limit <= 0:
            return []

        session_uuid = self._require_session_uuid(session_id)
        session_entity = await self._load_session(session_id)
        if session_entity is None:
            raise AppError("session not found", code=STB404_SESSION_NOT_FOUND, status=404)

        stmt = (
            select(models_study.StudyMessage)
            .where(models_study.StudyMessage.session_id == session_uuid)
            .order_by(desc(models_study.StudyMessage.created_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return list(reversed(rows))

    async def _load_session(self, session_id: str) -> models_study.StudySession | None:
        session_uuid = self._require_session_uuid(session_id)
        stmt = select(models_study.StudySession).where(models_study.StudySession.id == session_uuid)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _optional_uuid(value: Any) -> uuid.UUID | None:
        if value is None or value == "":
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _require_session_uuid(session_id: str) -> uuid.UUID:
        try:
            return session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive guard
            raise AppError("session not found", code=STB404_SESSION_NOT_FOUND, status=404) from exc
