# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""Study Buddy relational models.

Migration checklist:
1. Create new tables using Alembic migration `VXXXX__study_buddy.sql`, ensuring schemas align with Supabase RLS defaults.
2. Backfill `learning_material_id` references for existing topics where curated content already exists.
3. Populate initial StudySession rows for active quiz sessions if continuity is required (Attachment B §4).
4. Create indexes and policies before enabling feature flags to avoid downtime.
5. Validate foreign keys by running the provided `check_db_schema.py` script post-migration.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models import Base, pk_uuid, ts_now


LearningMaterialStatusEnum = sa.Enum(
    "draft",
    "published",
    "archived",
    name="learning_material_status",
    metadata=Base.metadata,
)

StudySessionModeEnum = sa.Enum(
    "reading",
    "quiz",
    "review",
    "planning",
    name="study_session_mode",
    metadata=Base.metadata,
)

StudySessionStatusEnum = sa.Enum(
    "active",
    "completed",
    "archived",
    "abandoned",
    name="study_session_status",
    metadata=Base.metadata,
)

StudyMessageRoleEnum = sa.Enum(
    "user",
    "assistant",
    "system",
    "tool",
    name="study_message_role",
    metadata=Base.metadata,
)

StudyMessageTypeEnum = sa.Enum(
    "chat",
    "hint",
    "summary",
    "plan",
    "system",
    name="study_message_type",
    metadata=Base.metadata,
)

QuestionOutcomeEnum = sa.Enum(
    "correct",
    "incorrect",
    "hint",
    "skipped",
    "unknown",
    name="study_question_outcome",
    metadata=Base.metadata,
)


class LearningMaterial(Base):
    """Top-level generated or curated learning material linked to topics and authored by admins.

    TODO:
    1. Store markdown content or S3 keys for generated artifacts and consider versioning strategy.
    2. Track publication workflow states (`draft`, `published`, `archived`) aligned with admin UI.
    3. Hydrate relationships to sections and study sessions for quick retrieval.

    Acceptance:
    - Table name aligns with migration and repository expectations.
    - Provides foreign keys for topic linkage and optional Supabase RLS scope.
    - Supports indexing on `(topic_id, created_at)` for fast lookups.
    """

    __tablename__ = "learning_materials"
    __table_args__ = (
        Index("ix_learning_materials_topic_created", "topic_id", "created_at"),
    )

    id: Mapped[_uuid.UUID] = pk_uuid()
    topic_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(sa.Text)
    content_markdown: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(
        LearningMaterialStatusEnum,
        nullable=False,
        server_default=sa.text("'draft'::learning_material_status"),
    )
    artifact_uri: Mapped[str | None] = mapped_column(sa.Text)
    requested_by: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))
    job_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("llm_jobs.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = ts_now()
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.text("now()"))

    topic = relationship("Topic")
    sections = relationship("LearningSection", back_populates="material", cascade="all, delete-orphan")
    sessions = relationship("StudySession", back_populates="material")

    def __repr__(self) -> str:
        """Return representation summarizing topic and status for debugging.

        TODO:
        1. Include key identifiers (topic_id, status) to simplify log inspection.
        2. Keep repr concise to avoid flooding logs with markdown content.
        3. Ensure sensitive data (e.g., artifact URI secrets) remain redacted.

        Acceptance:
        - repr output aids debugging without exposing full content.
        - Works even when optional fields are None.
        - Avoids expensive computations.
        """
        topic = getattr(self, "topic_id", None)
        status = getattr(self, "status", None)
        return f"LearningMaterial(id={self.id}, topic={topic}, status={status})"


class LearningSection(Base):
    """Content block belonging to a learning material, ordered for sequential study flows.

    TODO:
    1. Store both markdown and rendered HTML once pipelines support dual formats.
    2. Support analytics referencing section-level completion metrics.
    3. Include localization or translation metadata when available.

    Acceptance:
    - Maintains foreign key to parent learning material with cascade delete.
    - Orders sections deterministically using the `position` column.
    - Indexes support efficient retrieval by `(material_id, position)`.
    """

    __tablename__ = "learning_sections"
    __table_args__ = (
        Index("ix_learning_sections_material_position", "material_id", "position"),
    )

    id: Mapped[_uuid.UUID] = pk_uuid()
    material_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("learning_materials.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content_markdown: Mapped[str | None] = mapped_column(sa.Text)
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))

    created_at: Mapped[datetime] = ts_now()
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.text("now()"))

    material = relationship("LearningMaterial", back_populates="sections")

    def __repr__(self) -> str:
        """Return representation summarizing material linkage and ordering.

        TODO:
        1. Include material_id and position for quick triage in logs.
        2. Keep repr short to avoid leaking full markdown content.
        3. Handle None values gracefully.

        Acceptance:
        - repr output supports debugging while respecting privacy.
        - No expensive formatting beyond basic string interpolation.
        - Works in interactive shells when inspecting ORM instances.
        """
        return (
            "LearningSection(id={sid}, material={mid}, position={pos})".format(
                sid=self.id,
                mid=self.material_id,
                pos=self.position,
            )
        )


class StudySession(Base):
    """Study Buddy session metadata referencing users, topics, and optional linked materials or quizzes.

    TODO:
    1. Mirror Supabase row-level security patterns by storing Clerk user identifiers.
    2. Track session lifecycle states (active, completed, archived) for analytics.
    3. Store hint level counters and frustration signals for adaptive policies.

    Acceptance:
    - Primary key generated via `gen_random_uuid()` with created_at timestamps.
    - Indexed on `(user_clerk_id, created_at)` for recent session lookups.
    - Foreign keys maintain referential integrity with topics and learning materials.
    """

    __tablename__ = "study_sessions"
    __table_args__ = (
        Index("ix_study_sessions_user_created", "user_clerk_id", "created_at"),
        Index("ix_study_sessions_user_id_created", "user_id", "created_at"),
    )

    id: Mapped[_uuid.UUID] = pk_uuid()
    user_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))
    user_clerk_id: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    topic_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL"))
    material_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("learning_materials.id", ondelete="SET NULL"))
    linked_quiz_session_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"))

    mode: Mapped[str] = mapped_column(
        StudySessionModeEnum,
        nullable=False,
        server_default=sa.text("'reading'::study_session_mode"),
    )
    status: Mapped[str] = mapped_column(
        StudySessionStatusEnum,
        nullable=False,
        server_default=sa.text("'active'::study_session_status"),
    )
    hint_level: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, server_default=sa.text("0"))
    hint_budget: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, server_default=sa.text("3"))
    frustration_score: Mapped[int | None] = mapped_column(sa.SmallInteger)
    context_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = ts_now()
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.text("now()"))
    last_message_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    material = relationship("LearningMaterial", back_populates="sessions")
    messages = relationship("StudyMessage", back_populates="session", cascade="all, delete-orphan")
    question_history = relationship("QuestionHistory", back_populates="session", cascade="all, delete-orphan")
    analytics = relationship("StudyAnalytics", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        """Return string summarizing session identifiers and mode for logging.

        TODO:
        1. Include session UUID and user_clerk_id to aid troubleshooting.
        2. Omit verbose JSON context to keep repr concise.
        3. Ensure the method works even when relations are not loaded.

        Acceptance:
        - repr output helpful for debugging without overwhelming logs.
        - Safe when called before SQLAlchemy flush/commit.
        - Contains no secrets or large payloads.
        """
        return (
            "StudySession(id={sid}, user={user}, mode={mode}, status={status})".format(
                sid=self.id,
                user=self.user_clerk_id,
                mode=self.mode,
                status=self.status,
            )
        )


class StudyMessage(Base):
    """Conversation messages exchanged between learner and tutor during a study session.

    TODO:
    1. Flag tutor vs. learner messages using an enum for clarity and constraints.
    2. Store streaming metadata (token counts, latency) for analytics alignment.
    3. Provide indexing to retrieve recent messages quickly for context windows.

    Acceptance:
    - References StudySession with `ondelete=CASCADE` to maintain data hygiene.
    - Contains JSON metadata column for experiment flags or tool outputs.
    - Index on `(session_id, created_at)` supports chronological fetches.
    """

    __tablename__ = "study_messages"
    __table_args__ = (
        Index("ix_study_messages_session_created", "session_id", "created_at"),
    )

    id: Mapped[_uuid.UUID] = pk_uuid()
    session_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(StudyMessageRoleEnum, nullable=False)
    message_type: Mapped[str] = mapped_column(
        StudyMessageTypeEnum,
        nullable=False,
        server_default=sa.text("'chat'::study_message_type"),
    )
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    hint_level: Mapped[int | None] = mapped_column(sa.SmallInteger)
    tokens: Mapped[int | None] = mapped_column(sa.Integer)
    message_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    created_at: Mapped[datetime] = ts_now()

    session = relationship("StudySession", back_populates="messages")

    def __repr__(self) -> str:
        """Return representation including session ID, role, and truncated content preview.

        TODO:
        1. Limit content preview to avoid leaking sensitive answers or large strings.
        2. Include hint level for quick debugging of escalation flows.
        3. Ensure repr is safe before and after flush operations.

        Acceptance:
        - Provides succinct summary for logging while respecting privacy.
        - Works when metadata is None or missing fields.
        - Avoids heavy string manipulation.
        """
        preview = (self.content[:47] + "…") if self.content and len(self.content) > 48 else self.content
        return (
            "StudyMessage(id={mid}, session={sid}, role={role}, hint={hint}, type={mtype}, preview={preview})".format(
                mid=self.id,
                sid=self.session_id,
                role=self.role,
                hint=self.hint_level,
                mtype=self.message_type,
                preview=preview,
            )
        )


class QuestionHistory(Base):
    """History of quiz question attempts made during a study session to inform adaptive hints and analytics.

    TODO:
    1. Track correctness, attempt order, and any tutor interventions linked to each attempt.
    2. Link back to quiz attempts table when available for unified analytics.
    3. Provide indexes that support querying by question or session efficiently.

    Acceptance:
    - Maintains foreign keys to study sessions and quiz questions.
    - Stores payload metadata enabling post-hoc analysis of hint effectiveness.
    - Index on `(session_id, created_at)` ensures performant lookups.
    """

    __tablename__ = "study_question_history"
    __table_args__ = (
        Index("ix_study_question_history_session_created", "session_id", "created_at"),
        Index("ix_study_question_history_question_created", "question_id", "created_at"),
    )

    id: Mapped[_uuid.UUID] = pk_uuid()
    session_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("questions.id", ondelete="SET NULL"))
    user_answer: Mapped[str | None] = mapped_column(sa.Text)
    outcome: Mapped[str | None] = mapped_column(QuestionOutcomeEnum, nullable=True)
    history_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    created_at: Mapped[datetime] = ts_now()

    session = relationship("StudySession", back_populates="question_history")

    def __repr__(self) -> str:
        """Return representation summarizing question linkage and outcome for auditing.

        TODO:
        1. Include session_id and question_id for quick filtering in logs.
        2. Avoid printing full user answers to respect privacy policies.
        3. Display outcome classification succinctly (correct/incorrect/hint).

        Acceptance:
        - repr output aids debugging with minimal sensitive data exposure.
        - Works when optional fields are None or missing.
        - Does not trigger lazy loads.
        """
        return (
            "QuestionHistory(session={sid}, question={qid}, outcome={outcome})".format(
                sid=self.session_id,
                qid=self.question_id,
                outcome=self.outcome,
            )
        )


class StudyAnalytics(Base):
    """Aggregated analytics events tied to study sessions for personalization and reporting.

    TODO:
    1. Capture event types (e.g., frustration_update, hint_click) and structured payloads.
    2. Support TTL or archival policy to prevent unbounded growth.
    3. Index by `(session_id, created_at)` for chronological queries and dashboards.

    Acceptance:
    - Stores JSON payload with optional indexes (GIN) for query performance.
    - Maintains referential integrity with the parent study session.
    - Handles bulk inserts from worker processes without deadlocks.
    """

    __tablename__ = "study_analytics"
    __table_args__ = (
        Index("ix_study_analytics_session_created", "session_id", "created_at"),
        Index(
            "ix_study_analytics_payload_gin",
            "payload",
            postgresql_using="gin",
        ),
        Index("ix_study_analytics_event_type", "event_type"),
    )

    id: Mapped[_uuid.UUID] = pk_uuid()
    session_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = ts_now()

    session = relationship("StudySession", back_populates="analytics")

    def __repr__(self) -> str:
        """Return representation summarizing session, event type, and timestamp for logging.

        TODO:
        1. Include session_id and event_type in a concise string for debugging.
        2. Avoid dumping full payload JSON to keep logs light.
        3. Ensure repr works before the row is flushed (no assumption about created_at).

        Acceptance:
        - Provides quick debugging insight without overwhelming logs.
        - Handles None payload gracefully.
        - Deterministic output for snapshot testing.
        """
        return (
            "StudyAnalytics(id={aid}, session={sid}, event={event})".format(
                aid=self.id,
                sid=self.session_id,
                event=self.event_type,
            )
        )
