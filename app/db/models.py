"""ORM model declarations.

Maps to Section 4.2 of the design: Relational schema for users, sessions, topics,
questions, attempts, llm_jobs, pending_topics, and events.

Conventions:
- All PKs are UUID (gen_random_uuid()).
- Timestamps are timezone-aware, default now().
- External identifiers (ULID-like strings) ensure uniqueness at DB level:
  * topics.topic_uid UNIQUE
  * sessions.session_uid UNIQUE (also used as quiz_id in API)
  * sessions.quiz_uid UNIQUE  (explicit quiz identifier if distinct)
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, ClassVar, Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, UniqueConstraint, Index, text as sa_text
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base with naming conventions (lean)."""

    __table_args__: ClassVar[Any] = {"schema": None}


def pk_uuid() -> Mapped[_uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def ts_now() -> Mapped[datetime]:
    return mapped_column(sa.DateTime(timezone=True), server_default=sa.text("now()"))

class AppUser(Base):
    """Slim app user keyed by Clerk user id; all roles managed by Clerk."""
    __tablename__ = "app_users"

    id: Mapped[_uuid.UUID] = pk_uuid()
    clerk_user_id: Mapped[str] = mapped_column(sa.Text, unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(sa.Text)
    avatar_url: Mapped[str | None] = mapped_column(sa.Text)
    # role column removed - roles are managed by Clerk, not stored in database
    
    # Profile fields (added by colleague in 0008_add_profile_fields)
    profile_complete: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.text("false"), nullable=False)
    age: Mapped[int | None] = mapped_column(sa.Integer)
    highest_education_level: Mapped[str | None] = mapped_column(sa.Text)
    subjects_of_interest: Mapped[list[str] | None] = mapped_column(sa.JSON)

    # TODO: FUTURE ORG FEATURE - Uncomment when implementing organizations
    # org_id: Mapped[_uuid.UUID | None] = mapped_column(sa.ForeignKey("organizations.id"), nullable=True)
    # org_role: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # org_slug: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    created_at: Mapped[datetime] = ts_now()
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.text("now()"))

    # Keep relationship name stable ("user") so existing code compiles until Stage 4
    sessions: Mapped[list["Session"]] = relationship(back_populates="user")
    quiz_summaries: Mapped[list["QuizSummary"]] = relationship(back_populates="user")

# Temporary alias to reduce ripple until Stage 4 rewrites


# Temporary alias to reduce ripple until Stage 4 rewrites



class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_topics_slug"),
        UniqueConstraint("name", name="uq_topics_name"),
    )

    id: Mapped[_uuid.UUID] = pk_uuid()
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    slug: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(sa.Text)

    # --- Module 2 flags ---
    is_published: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.text("false"))
    is_deleted: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.text("false"))

    created_at: Mapped[datetime] = ts_now()
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.text("now()"))

    questions: Mapped[list["Question"]] = relationship(back_populates="topic")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("question_hash", name="uq_questions_question_hash"),
        sa.Index("ix_questions_topic_difficulty", "topic_id", "difficulty"),
    )

    id: Mapped[_uuid.UUID] = pk_uuid()
    topic_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    difficulty: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    choices: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correct_answer: Mapped[str] = mapped_column(sa.Text, nullable=False)
    explanations: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[str | None] = mapped_column(sa.Text)
    question_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)

    created_at: Mapped[datetime] = ts_now()

    topic: Mapped["Topic"] = relationship(back_populates="questions")


class Session(Base):
    """Quiz session (aka 'quiz run')."""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("session_uid", name="uq_sessions_session_uid"),
        UniqueConstraint("quiz_uid", name="uq_sessions_quiz_uid"),
    )

    id: Mapped[_uuid.UUID] = pk_uuid()
    user_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    topic_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL"))

    session_uid: Mapped[str] = mapped_column(sa.Text, nullable=False)
    quiz_uid: Mapped[str] = mapped_column(sa.Text, nullable=False)

    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="active")
    started_at: Mapped[datetime] = ts_now()
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    # --- Adaptive fields (Module 1) ---
    current_difficulty: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, server_default=sa.text("3"))
    streak_correct: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    streak_wrong: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    mastery_reached: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.text("false"))


    created_at: Mapped[datetime] = ts_now()

    user: Mapped["AppUser"] = relationship(back_populates="sessions")
    topic: Mapped["Topic | None"] = relationship()
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="session")
    summary: Mapped["QuizSummary | None"] = relationship(back_populates="session", uselist=False)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        sa.Index("ix_attempts_session", "session_id"),
        sa.Index("ix_attempts_session_question", "session_id", "question_id"),
        UniqueConstraint("session_id", "question_id", name="uq_attempts_session_question"),
    )

    id: Mapped[_uuid.UUID] = pk_uuid()
    session_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)

    selected_answer: Mapped[str | None] = mapped_column(sa.Text)
    is_correct: Mapped[bool | None] = mapped_column(sa.Boolean)

    elapsed_ms: Mapped[int | None] = mapped_column(sa.Integer)

    created_at: Mapped[datetime] = ts_now()

    session: Mapped["Session"] = relationship(back_populates="attempts")
    question: Mapped["Question"] = relationship()


class QuizSummary(Base):
    """Cached quiz attempt summary for efficient history queries."""

    __tablename__ = "quiz_summaries"

    id: Mapped[_uuid.UUID] = pk_uuid()
    session_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False)
    topic_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL"))

    total_attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa_text("0"))
    correct_answers: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa_text("0"))
    accuracy: Mapped[float] = mapped_column(sa.Numeric(5, 4), nullable=False, server_default=sa_text("0.0"))  # 0.0000 to 1.0000
    final_difficulty: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, server_default=sa_text("3"))
    mastery_reached: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa_text("false"))

    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = ts_now()
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa_text("now()"))

    session: Mapped["Session"] = relationship(back_populates="summary")
    user: Mapped["AppUser"] = relationship(back_populates="quiz_summaries")
    topic: Mapped["Topic | None"] = relationship()

class LLMJob(Base):
    __tablename__ = "llm_jobs"

    id: Mapped[_uuid.UUID] = pk_uuid()
    job_type: Mapped[str] = mapped_column(sa.Text, nullable=False, default="generate_topic")
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="queued")
    priority: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, default=5)

    topic_slug: Mapped[str | None] = mapped_column(sa.Text)
    topic_name: Mapped[str | None] = mapped_column(sa.Text)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    requested_by: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))

    error: Mapped[str | None] = mapped_column(sa.Text)
    retry_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    # --- Module 3 outcome fields ---
    created_count: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    artifact_s3_key: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)

    created_at: Mapped[datetime] = ts_now()
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()")
    )


class PendingTopic(Base):
    __tablename__ = "pending_topics"
    __table_args__ = (UniqueConstraint("topic_slug", name="uq_pending_topics_topic_slug"),)

    id: Mapped[_uuid.UUID] = pk_uuid()
    topic_slug: Mapped[str] = mapped_column(sa.Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(sa.Text)

    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="queued")
    requested_by: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = ts_now()
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()")
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[_uuid.UUID] = pk_uuid()
    session_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True)
    user_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)  # or server_default=sa.text("'{}'::jsonb")

    created_at: Mapped[datetime] = ts_now()
