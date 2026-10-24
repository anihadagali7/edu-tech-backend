"""Database repository helpers for topics, questions, and search enqueue.

Maps to Section 4.4 of the design: Persistence layer helpers used by features.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMJob, PendingTopic, Question, Topic, Event, AppUser as User, Session, Attempt, QuizSummary
from app.utils.errors import AppError, TOP404_NOT_FOUND, TOP409_DUPLICATE_SLUG
from app.utils.ids import new_ulid
from datetime import datetime


@dataclass(frozen=True)
class TopicRow:
    id: str
    name: str
    slug: str
    description: str | None
    is_published: bool
    is_deleted: bool


async def get_topic_by_id(db: AsyncSession, topic_id: UUID, *, include_deleted: bool = False) -> Optional[TopicRow]:
    """Fetch a topic by UUID."""
    stmt = select(Topic).where(Topic.id == topic_id)
    if not include_deleted:
        stmt = stmt.where(Topic.is_deleted.is_(False))
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        return None
    return TopicRow(
        id=str(row.id),
        name=row.name,
        slug=row.slug,
        description=row.description,
        is_published=bool(row.is_published),
        is_deleted=bool(row.is_deleted),
    )


async def get_topic_by_slug(db: AsyncSession, slug: str, *, include_deleted: bool = False) -> Optional[TopicRow]:
    """Fetch a topic by slug."""
    stmt = select(Topic).where(Topic.slug == slug)
    if not include_deleted:
        stmt = stmt.where(Topic.is_deleted.is_(False))
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        return None
    return TopicRow(
        id=str(row.id),
        name=row.name,
        slug=row.slug,
        description=row.description,
        is_published=bool(row.is_published),
        is_deleted=bool(row.is_deleted),
    )


async def list_topics(
    db: AsyncSession,
    *,
    q: str | None = None,
    parent_id: UUID | None = None,  # future-proof; currently unused
    published_only: bool = True,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List topics with optional fuzzy match on name/slug and publication filters."""
    # Build base query for filtering
    base_stmt = select(Topic)

    if q:
        like = f"%{q.lower()}%"
        base_stmt = base_stmt.where(or_(func.lower(Topic.name).like(like), func.lower(Topic.slug).like(like)))

    if published_only:
        base_stmt = base_stmt.where(Topic.is_published.is_(True))

    if not include_deleted:
        base_stmt = base_stmt.where(Topic.is_deleted.is_(False))

    # Count total matching topics
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = int((await db.execute(count_stmt)).scalar_one())

    # Get paginated results
    stmt = base_stmt.order_by(Topic.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    rows = res.scalars().all()
    
    items = [
        TopicRow(
            id=str(t.id),
            name=t.name,
            slug=t.slug,
            description=t.description,
            is_published=bool(t.is_published),
            is_deleted=bool(t.is_deleted),
        )
        for t in rows
    ]
    
    return {"items": items, "total": total}


async def count_questions_by_topic(db: AsyncSession, topic_id: UUID) -> int:
    """Count questions under a topic."""
    stmt = select(func.count(Question.id)).where(Question.topic_id == topic_id)
    res = await db.execute(stmt)
    return int(res.scalar_one())


async def count_total_questions(db: AsyncSession) -> int:
    """Count questions """
    stmt = select(func.count(Question.id))
    res = await db.execute(stmt)
    return int(res.scalar_one())


# ----------------- Search enqueue helpers -----------------


async def upsert_pending_topic_and_job(
    db: AsyncSession,
    *,
    topic_slug: str,
    display_name: str | None,
    requested_by: UUID | None,
) -> dict:
    """Idempotently ensure a pending topic and a queued LLM job exist.

    Returns:
        {
          "pending_topic": {"topic_slug": str},
          "job_id": Optional[str]
        }
    """
    # Upsert pending topic
    pt_stmt = (
        pg_insert(PendingTopic)
        .values(topic_slug=topic_slug, display_name=display_name, requested_by=requested_by, status="queued")
        .on_conflict_do_nothing(index_elements=[PendingTopic.topic_slug])
        .returning(PendingTopic.id, PendingTopic.topic_slug)
    )
    pt_res = await db.execute(pt_stmt)
    pt_row = pt_res.first()
    if not pt_row:
        # pre-existing row; fetch it
        pt_row = (await db.execute(select(PendingTopic.id, PendingTopic.topic_slug).where(PendingTopic.topic_slug == topic_slug))).one()

    # Best-effort enqueue: avoid duplicate storms by attempting a loose ON CONFLICT (no natural key)
    job_stmt = (
        pg_insert(LLMJob)
        .values(
            job_type="generate_topic",
            status="queued",
            priority=5,
            topic_slug=topic_slug,
            topic_name=display_name,  # Use the display_name provided
            requested_by=requested_by,
        )
        .returning(LLMJob.id)
    )
    job_id: str | None = None
    try:
        j_res = await db.execute(job_stmt)
        row = j_res.first()
        if row:
            job_id = str(row.id)
    except Exception:
        # If there is some implicit uniqueness via a partial index in future,
        # treat insert errors as "already enqueued".
        job_id = None

    return {"pending_topic": {"topic_slug": pt_row.topic_slug}, "job_id": job_id}


# ----------------- Admin Topic CRUD -----------------


async def admin_create_topic(
    db: AsyncSession,
    *,
    name: str,
    slug: str,
    description: str | None,
    is_published: bool = False,
) -> TopicRow:
    """Create a curated topic; enforce slug uniqueness."""
    # Enforce slug uniqueness early to return a friendly error
    exists = (await db.execute(select(Topic.id).where(Topic.slug == slug))).scalar_one_or_none()
    if exists:
        raise AppError("duplicate slug", code=TOP409_DUPLICATE_SLUG, status=409)

    stmt = (
        pg_insert(Topic)
        .values(name=name, slug=slug, description=description, is_published=is_published, is_deleted=False)
        .returning(
            Topic.id,
            Topic.name,
            Topic.slug,
            Topic.description,
            Topic.is_published,
            Topic.is_deleted,
        )
    )
    res = await db.execute(stmt)
    row = res.one()
    return TopicRow(
        id=str(row.id),
        name=row.name,
        slug=row.slug,
        description=row.description,
        is_published=bool(row.is_published),
        is_deleted=bool(row.is_deleted),
    )


async def admin_update_topic(
    db: AsyncSession,
    *,
    topic_id: UUID,
    name: str | None = None,
    slug: str | None = None,
    description: str | None = None,
    is_published: bool | None = None,
) -> TopicRow:
    """Update a topic; maintain slug uniqueness and return the row."""
    # Check existence
    existing = (await db.execute(select(Topic).where(Topic.id == topic_id))).scalar_one_or_none()
    if not existing:
        raise AppError("topic not found", code=TOP404_NOT_FOUND, status=404)

    # Slug uniqueness if changing slug
    if slug and slug != existing.slug:
        exists = (await db.execute(select(Topic.id).where(Topic.slug == slug))).scalar_one_or_none()
        if exists:
            raise AppError("duplicate slug", code=TOP409_DUPLICATE_SLUG, status=409)

    values: dict = {}
    if name is not None:
        values["name"] = name
    if slug is not None:
        values["slug"] = slug
    if description is not None:
        values["description"] = description
    if is_published is not None:
        values["is_published"] = is_published

    if not values:
        # no-op; return existing
        return TopicRow(
            id=str(existing.id),
            name=existing.name,
            slug=existing.slug,
            description=existing.description,
            is_published=bool(existing.is_published),
            is_deleted=bool(existing.is_deleted),
        )

    stmt = (
        update(Topic)
        .where(Topic.id == topic_id)
        .values(**values)
        .returning(
            Topic.id,
            Topic.name,
            Topic.slug,
            Topic.description,
            Topic.is_published,
            Topic.is_deleted,
        )
    )
    res = await db.execute(stmt)
    row = res.one()
    return TopicRow(
        id=str(row.id),
        name=row.name,
        slug=row.slug,
        description=row.description,
        is_published=bool(row.is_published),
        is_deleted=bool(row.is_deleted),
    )


async def admin_delete_topic(db: AsyncSession, *, topic_id: UUID, soft: bool = True) -> None:
    """Delete or soft-delete a topic."""
    if soft:
        stmt = update(Topic).where(Topic.id == topic_id).values(is_deleted=True)
        res = await db.execute(stmt)
        if res.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError("topic not found", code=TOP404_NOT_FOUND, status=404)
    else:
        # Hard delete; will cascade to questions per FK on CASCADE if configured
        result = await db.execute(sa.delete(Topic).where(Topic.id == topic_id))
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError("topic not found", code=TOP404_NOT_FOUND, status=404)


# ----------------- Bulk import questions -----------------

@dataclass(frozen=True)
class ImportItem:
    body: str
    choices: dict
    correct_answer: str
    difficulty: int
    question_hash: str  # precomputed by worker/ingester


async def bulk_upsert_questions(
    db: AsyncSession,
    *,
    topic_id: UUID,
    items: Iterable[ImportItem],
) -> dict:
    """Bulk insert questions; de-dup by `question_hash`.

    Returns:
        {"created_count": int, "duplicate_count": int}
    """
    # Prepare rows
    rows = [
        {
            "topic_id": topic_id,
            "difficulty": int(i.difficulty),
            "body": i.body,
            "choices": i.choices,
            "correct_answer": i.correct_answer,
            "question_hash": i.question_hash,
        }
        for i in items
    ]
    if not rows:
        return {"created_count": 0, "duplicate_count": 0}

    stmt = (
        pg_insert(Question)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[Question.question_hash])
        .returning(Question.id)
    )
    res = await db.execute(stmt)
    created_ids = [r.id for r in res]
    created = len(created_ids)
    duplicates = max(0, len(rows) - created)
    return {"created_count": created, "duplicate_count": duplicates}



# ----------------- NEW: Admin reporting helpers -----------------

async def admin_list_users(
    db: AsyncSession,
    *,
    q: str | None = None,
    role: str | None = None,  # Not used - roles managed by Clerk, kept for API compatibility
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List users for admin reporting.
    
    Note: Role filtering is not available as roles are managed by Clerk and not stored in the database.
    """
    base = select(
        User.id, 
        User.clerk_user_id, 
        User.full_name, 
        User.avatar_url, 
        User.profile_complete,
        User.age,
        User.highest_education_level,
        User.subjects_of_interest,
        User.created_at
    )

    conds: list[Any] = []
    if q:
        like = f"%{q.lower()}%"
        conds.append(or_(func.lower(User.clerk_user_id).like(like), func.lower(User.full_name).like(like)))
    # Note: role filtering removed - roles are managed by Clerk, not stored in DB
    if created_from:
        conds.append(User.created_at >= created_from)
    if created_to:
        conds.append(User.created_at <= created_to)

    if conds:
        base = base.where(and_(*conds))

    total_stmt = select(func.count()).select_from(base.subquery())
    total = int((await db.execute(total_stmt)).scalar_one())

    stmt = base.order_by(User.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    items = []
    for r in res.all():
        items.append(
        {
            "id": str(r.id),
            "clerk_user_id": r.clerk_user_id,
            "full_name": r.full_name,
            "avatar_url": r.avatar_url,
            "profile_complete": r.profile_complete,
            "age": r.age,
            "highest_education_level": r.highest_education_level,
            "subjects_of_interest": r.subjects_of_interest or [],
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        )
        
    return {"items": items, "total": total}


async def admin_list_events(
    db: AsyncSession,
    *,
    event_type: str | None = None,
    user_id: UUID | None = None,
    session_id: UUID | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List audit events with optional filters."""
    base = select(Event.id, Event.user_id, Event.session_id, Event.event_type, Event.payload, Event.created_at)
    conds: list[Any] = []
    if event_type:
        conds.append(Event.event_type == event_type)
    if user_id:
        conds.append(Event.user_id == user_id)
    if session_id:
        conds.append(Event.session_id == session_id)
    if from_ts:
        conds.append(Event.created_at >= from_ts)
    if to_ts:
        conds.append(Event.created_at <= to_ts)
    if conds:
        base = base.where(and_(*conds))

    total_stmt = select(func.count()).select_from(base.subquery())
    total = int((await db.execute(total_stmt)).scalar_one())

    stmt = base.order_by(Event.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    items = [
        {
            "id": str(r.id),
            "user_id": (str(r.user_id) if r.user_id else None),
            "session_id": (str(r.session_id) if r.session_id else None),
            "event_type": r.event_type,
            "payload": r.payload,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in res.all()
    ]
    return {"items": items, "total": total}


async def admin_snapshot_topics(
    db: AsyncSession,
    *,
    include_unpublished: bool = False,
) -> list[dict]:
    """Return a snapshot of topics for exports."""
    stmt = select(
        Topic.id,
        Topic.name,
        Topic.slug,
        Topic.description,
        Topic.is_published,
        Topic.is_deleted,
        Topic.created_at,
        Topic.updated_at,
    )
    if not include_unpublished:
        stmt = stmt.where(Topic.is_published.is_(True))
    stmt = stmt.where(Topic.is_deleted.is_(False)).order_by(Topic.created_at.desc())

    res = await db.execute(stmt)
    rows = res.all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "slug": r.slug,
            "description": r.description,
            "is_published": bool(r.is_published),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


async def list_user_sessions(
    db: AsyncSession,
    *,
    user_id: UUID,
    topic_id: UUID | None = None,
    status: str | None = "completed",  # Default to completed for history
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    min_accuracy: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List quiz sessions for a user with filters. Uses quiz_summaries table for efficient queries.
    
    For paused sessions, queries Session table directly since they don't have summaries yet.
    """
    # If querying paused sessions, use Session table directly (no summaries exist yet)
    if status == "paused":
        base = select(
            Session.id.label("session_id"),
            Session.user_id,
            Session.topic_id,
            Session.session_uid,
            Session.started_at,
            Session.status,
            Session.current_difficulty,
            Session.mastery_reached,
            Session.ended_at,
            func.count(Attempt.id).label("total_attempts"),
            func.sum(func.cast(Attempt.is_correct, sa.Integer)).label("correct_answers"),
        ).outerjoin(Attempt, Attempt.session_id == Session.id).where(
            Session.user_id == user_id,
            Session.status == "paused"
        ).group_by(
            Session.id, Session.user_id, Session.topic_id, Session.session_uid,
            Session.started_at, Session.status, Session.current_difficulty,
            Session.mastery_reached, Session.ended_at
        )
        
        conds: list[Any] = []
        
        if topic_id:
            conds.append(Session.topic_id == topic_id)
        
        if conds:
            base = base.where(and_(*conds))
        
        # Get total count
        total_stmt = select(func.count()).select_from(base.subquery())
        total = int((await db.execute(total_stmt)).scalar_one())
        
        # Get paginated results
        stmt = base.order_by(Session.started_at.desc()).limit(limit).offset(offset)
        res = await db.execute(stmt)
        
        items = []
        for r in res.all():
            total_attempts = int(r.total_attempts or 0)
            correct_answers = int(r.correct_answers or 0)
            accuracy = (correct_answers / total_attempts) if total_attempts > 0 else 0.0
            
            items.append({
                "session_uid": r.session_uid,
                "session_id": str(r.session_id),
                "topic_id": str(r.topic_id) if r.topic_id else None,
                "total_attempts": total_attempts,
                "correct_answers": correct_answers,
                "accuracy": accuracy,
                "final_difficulty": r.current_difficulty,
                "mastery_reached": bool(r.mastery_reached),
                "ended_at": None,  # Paused sessions don't have ended_at
                "started_at": r.started_at.isoformat() if r.started_at else None,
            })
        
        return {"items": items, "total": total}
    
    # For completed/active sessions, use quiz_summaries for performance
    # Start with quiz_summaries for performance
    base = select(
        QuizSummary.session_id,
        QuizSummary.user_id,
        QuizSummary.topic_id,
        QuizSummary.total_attempts,
        QuizSummary.correct_answers,
        QuizSummary.accuracy,
        QuizSummary.final_difficulty,
        QuizSummary.mastery_reached,
        QuizSummary.ended_at,
        QuizSummary.created_at,
        Session.session_uid,
        Session.started_at,
    ).join(Session, Session.id == QuizSummary.session_id)
    
    conds: list[Any] = [QuizSummary.user_id == user_id]
    
    if topic_id:
        conds.append(QuizSummary.topic_id == topic_id)
    
    if status:
        conds.append(Session.status == status)
    else:
        # If no status specified, get all completed
        conds.append(Session.status == "completed")
    
    if from_date:
        conds.append(QuizSummary.ended_at >= from_date)
    
    if to_date:
        conds.append(QuizSummary.ended_at <= to_date)
    
    if min_accuracy is not None:
        conds.append(QuizSummary.accuracy >= min_accuracy)
    
    if conds:
        base = base.where(and_(*conds))
    
    # Get total count
    total_stmt = select(func.count()).select_from(base.subquery())
    total = int((await db.execute(total_stmt)).scalar_one())
    
    # Get paginated results, ordered by most recent first
    stmt = base.order_by(QuizSummary.ended_at.desc().nullslast()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    
    items = []
    for r in res.all():
        items.append({
            "session_uid": r.session_uid,
            "session_id": str(r.session_id),
            "topic_id": str(r.topic_id) if r.topic_id else None,
            "total_attempts": r.total_attempts,
            "correct_answers": r.correct_answers,
            "accuracy": float(r.accuracy) if r.accuracy else 0.0,
            "final_difficulty": r.final_difficulty,
            "mastery_reached": bool(r.mastery_reached),
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "started_at": r.started_at.isoformat() if r.started_at else None,
        })
    
    return {"items": items, "total": total}


async def get_session_details_with_attempts(
    db: AsyncSession,
    *,
    session_uid: str,
    user_id: UUID,
) -> dict | None:
    """Get detailed session history with all attempts, questions, and answers for review."""
    # Get session with topic info
    session_stmt = select(
        Session.id,
        Session.session_uid,
        Session.user_id,
        Session.topic_id,
        Session.status,
        Session.started_at,
        Session.ended_at,
        Session.current_difficulty,
        Session.mastery_reached,
        Topic.name.label("topic_name"),
        Topic.slug.label("topic_slug"),
    ).join(Topic, Topic.id == Session.topic_id, isouter=True).where(
        Session.session_uid == session_uid
    )
    
    session_result = await db.execute(session_stmt)
    session_row = session_result.first()
    
    if not session_row:
        return None
    
    # Verify ownership (user must own session unless admin - but we'll check in the endpoint)
    if session_row.user_id != user_id:
        return None
    
    # Get all attempts with questions
    attempts_stmt = select(
        Attempt.id,
        Attempt.question_id,
        Attempt.selected_answer,
        Attempt.is_correct,
        Attempt.elapsed_ms,
        Attempt.created_at,
        Question.body,
        Question.choices,
        Question.correct_answer,
        Question.difficulty,
        Question.explanations,
    ).join(
        Question, Question.id == Attempt.question_id
    ).where(
        Attempt.session_id == session_row.id
    ).order_by(
        Attempt.created_at.asc()  # Order by when answered
    )
    
    attempts_result = await db.execute(attempts_stmt)
    attempts_rows = attempts_result.all()
    
    attempts = []
    for a in attempts_rows:
        attempts.append({
            "attempt_id": str(a.id),
            "question_id": str(a.question_id),
            "question_body": a.body,
            "question_difficulty": a.difficulty,
            "choices": a.choices,  # dict with A, B, C, D
            "correct_answer": a.correct_answer,
            "selected_answer": a.selected_answer,
            "is_correct": bool(a.is_correct) if a.is_correct is not None else None,
            "elapsed_ms": a.elapsed_ms,
            "answered_at": a.created_at.isoformat() if a.created_at else None,
            "explanations": a.explanations or {},  # dict with explanations
        })
    
    # Get summary if available
    summary_stmt = select(QuizSummary).where(QuizSummary.session_id == session_row.id)
    summary_result = await db.execute(summary_stmt)
    summary = summary_result.scalar_one_or_none()
    
    return {
        "session_uid": session_row.session_uid,
        "session_id": str(session_row.id),
        "topic_id": str(session_row.topic_id) if session_row.topic_id else None,
        "topic_name": session_row.topic_name,
        "topic_slug": session_row.topic_slug,
        "status": session_row.status,
        "started_at": session_row.started_at.isoformat() if session_row.started_at else None,
        "ended_at": session_row.ended_at.isoformat() if session_row.ended_at else None,
        "current_difficulty": session_row.current_difficulty,
        "mastery_reached": bool(session_row.mastery_reached),
        "attempts": attempts,
        "summary": {
            "total_attempts": summary.total_attempts if summary else len(attempts),
            "correct_answers": summary.correct_answers if summary else sum(1 for a in attempts if a["is_correct"]),
            "accuracy": float(summary.accuracy) if summary and summary.accuracy else (sum(1 for a in attempts if a["is_correct"]) / len(attempts) if attempts else 0.0),
            "final_difficulty": summary.final_difficulty if summary else session_row.current_difficulty,
            "mastery_reached": bool(summary.mastery_reached) if summary else bool(session_row.mastery_reached),
        } if summary or attempts else None,
    }


async def upsert_quiz_summary(
    db: AsyncSession,
    *,
    session_id: UUID,
    user_id: UUID,
    topic_id: UUID | None,
    total_attempts: int,
    correct_answers: int,
    accuracy: float,
    final_difficulty: int,
    mastery_reached: bool,
    ended_at: datetime | None,
) -> QuizSummary:
    """Create or update quiz summary in the cache table."""
    stmt = (
        pg_insert(QuizSummary)
        .values(
            session_id=session_id,
            user_id=user_id,
            topic_id=topic_id,
            total_attempts=total_attempts,
            correct_answers=correct_answers,
            accuracy=accuracy,
            final_difficulty=final_difficulty,
            mastery_reached=mastery_reached,
            ended_at=ended_at,
            updated_at=sa.text("now()"),
        )
        .on_conflict_do_update(
            index_elements=["session_id"],
            set_=dict(
                total_attempts=sa.text("EXCLUDED.total_attempts"),
                correct_answers=sa.text("EXCLUDED.correct_answers"),
                accuracy=sa.text("EXCLUDED.accuracy"),
                final_difficulty=sa.text("EXCLUDED.final_difficulty"),
                mastery_reached=sa.text("EXCLUDED.mastery_reached"),
                ended_at=sa.text("EXCLUDED.ended_at"),
                updated_at=sa.text("now()"),
            ),
        )
        .returning(QuizSummary)
    )
    
    result = await db.execute(stmt)
    summary = result.scalar_one()
    return summary
