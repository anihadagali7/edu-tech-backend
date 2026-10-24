"""Adaptive quiz service implementation.

Maps to Section 5.3 of the design: Adaptive state machine, difficulty selection,
and progression with transactional semantics and RBAC ownership checks.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional
from uuid import UUID

import sqlalchemy as sa
from slugify import slugify
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Attempt, Event, Question, Session, Topic, LLMJob, PendingTopic, AppUser as User
from app.db.repositories import upsert_quiz_summary
from app.utils.errors import AppError, QZ404_SESSION_NOT_FOUND, QZ409_DUPLICATE_ANSWER, USR404_NOT_FOUND
from app.utils.ids import new_ulid

log = logging.getLogger("quizzes")

@dataclass(frozen=True)
class QuestionView:
    id: str
    body: str
    choices: dict
    difficulty: int

@dataclass(frozen=True)
class SessionView:
    session_uid: str
    quiz_uid: str
    topic_id: Optional[str]
    current_difficulty: int
    needs_refill: bool = False


def _diff_search_order(base: int) -> list[int]:
    order: list[int] = [base]
    for delta in (1, 2):
        if base - delta >= 1:
            order.append(base - delta)
        if base + delta <= 5:
            order.append(base + delta)
    # ensure unique & preserve order
    seen: set[int] = set()
    uniq: list[int] = []
    for d in order:
        if d not in seen:
            uniq.append(d)
            seen.add(d)
    return uniq


async def _select_next_question(
    session: AsyncSession,
    *,
    session_id: UUID,
    topic_id: UUID,
    desired_difficulty: int,
) -> Optional[QuestionView]:
    """Pick the next unseen question using SKIP LOCKED, falling back to nearby difficulties.
    
    Optimized to use LEFT JOIN instead of NOT EXISTS subquery for better performance,
    especially with the composite index on (session_id, question_id).
    """
    for level in _diff_search_order(desired_difficulty):
        # Use LEFT JOIN to exclude answered questions - faster than NOT EXISTS subquery
        # The composite index on (session_id, question_id) makes this very efficient
        q = (
            select(Question)
            .outerjoin(
                Attempt,
                and_(
                    Attempt.session_id == session_id,
                    Attempt.question_id == Question.id
                )
            )
            .where(
                and_(
                    Question.topic_id == topic_id,
                    Question.difficulty == level,
                    Attempt.id.is_(None)  # Only questions with no attempt for this session
                )
            )
            .order_by(Question.id.asc())
            .with_for_update(skip_locked=True, of=Question)
            .limit(1)
        )
        res = await session.execute(q)
        row = res.scalar_one_or_none()
        if row:
            return QuestionView(id=str(row.id), body=row.body, choices=row.choices, difficulty=row.difficulty)
    return None


async def _create_quiz_session(
    session: AsyncSession,
    *,
    user_id: UUID,
    topic_id: Optional[UUID],
    initial_difficulty: int = 3,
) -> SessionView:
    s_uid = new_ulid()
    q_uid = new_ulid()
    stmt = (
        pg_insert(Session)
        .values(
            user_id=user_id,
            topic_id=topic_id,
            session_uid=s_uid,
            quiz_uid=q_uid,
            status="initialized",  # Changed from "active" - will be marked "active" when first answer is submitted
            current_difficulty=initial_difficulty,
            streak_correct=0,
            streak_wrong=0,
            mastery_reached=False,
        )
        .returning(
            Session.id,
            Session.session_uid,
            Session.quiz_uid,
            Session.topic_id,
            Session.current_difficulty,
        )
    )
    res = await session.execute(stmt)
    (sid, session_uid, quiz_uid, topic_fk, cur_diff) = res.one()
    await session.execute(
        pg_insert(Event).values(
            session_id=sid, user_id=user_id, event_type="QUIZ_START", payload={"topic_id": str(topic_fk) if topic_fk else None}
        )
    )
    return SessionView(session_uid=session_uid, quiz_uid=quiz_uid, topic_id=str(topic_fk) if topic_fk else None, current_difficulty=cur_diff)


async def _ensure_topic_by_name(
    session: AsyncSession,
    *,
    topic_name: str,
    requested_by: Optional[UUID],
) -> Topic:
    """Idempotently ensure a placeholder topic + pending job for a given name."""
    slug = slugify(topic_name)
    # Try find existing
    res = await session.execute(select(Topic).where(Topic.slug == slug))
    existing = res.scalar_one_or_none()
    if existing:
        return existing

    # Insert placeholder topic (ON CONFLICT DO NOTHING by slug)
    t_ins = (
        pg_insert(Topic)
        .values(name=topic_name, slug=slug, description=None)
        .on_conflict_do_nothing(index_elements=[Topic.slug])
        .returning(Topic.id, Topic.slug, Topic.name)
    )
    t_res = await session.execute(t_ins)
    row = t_res.first()
    if not row:
        # A concurrent insert won; fetch it
        existing2 = (await session.execute(select(Topic).where(Topic.slug == slug))).scalar_one()
        topic = existing2
    else:
        topic = (await session.execute(select(Topic).where(Topic.id == row.id))).scalar_one()

    # Upsert pending_topics
    await session.execute(
        pg_insert(PendingTopic)
        .values(topic_slug=slug, display_name=topic_name, requested_by=requested_by, status="queued")
        .on_conflict_do_nothing(index_elements=[PendingTopic.topic_slug])
    )
    # Enqueue LLM job (avoid duplicates if a queued/running job exists)
    # Check if there is already a queued or running job for this slug
    existing_job = (
        await session.execute(
            select(LLMJob.id).where(and_(LLMJob.topic_slug == slug, LLMJob.status.in_(["queued", "running"]))).limit(1)
        )
    ).scalar_one_or_none()
    if not existing_job:
        await session.execute(
            pg_insert(LLMJob)
            .values(job_type="generate_topic", status="queued", topic_slug=slug, requested_by=requested_by, priority=5)
            .on_conflict_do_nothing()  # DB-level partial index will also help prevent duplicates
        )
    return topic


class AdaptiveService:
    """Facade for adaptive quiz operations."""

    # ---- PUBLIC API ----

    async def start_quiz(
        self,
        *,
        db: AsyncSession,
        actor_id: UUID,
        topic_id: Optional[UUID],
        topic_name: Optional[str] = None,
        difficulty_hint: Optional[int] = None,
    ) -> dict[str, Any]:
        """Create a new session and (optionally) select the first question.

        Returns:
            {
              "session": SessionView,
              "first_question": QuestionView | None
            }
        """
        init_diff = difficulty_hint or 3
        init_diff = min(5, max(1, int(init_diff)))

        # Resolve topic if only name provided
        topic_obj: Optional[Topic] = None
        if topic_id is None and topic_name:
            topic_obj = await _ensure_topic_by_name(db, topic_name=topic_name, requested_by=actor_id)
            topic_id = topic_obj.id
        elif topic_id is not None:
            # ensure it exists
            res = await db.execute(select(Topic).where(Topic.id == topic_id))
            topic_obj = res.scalar_one_or_none()
            if not topic_obj:
                raise AppError("topic not found", code="TOP404_NOT_FOUND", status=404)

        # Create session + pick first question in one transaction
        sv = await _create_quiz_session(db, user_id=actor_id, topic_id=topic_id, initial_difficulty=init_diff)
        first_q: Optional[QuestionView] = None
        needs_refill = False
        if topic_id:
            first_q = await _select_next_question(db, session_id=UUID(sv.session_uid), topic_id=topic_id, desired_difficulty=sv.current_difficulty)  # type: ignore[arg-type]
            # ^ NOTE: session_id here must be DB UUID, but we only returned session_uid.
            # Workaround: fetch session row just created to get its UUID.
            # Adjust: Re-fetch by session_uid.
        # Re-fetch session row (UUID id)
        sess_row = (
            await db.execute(select(Session).where(Session.session_uid == sv.session_uid).with_for_update())
        ).scalar_one()
        if topic_id:
            first_q = await _select_next_question(db, session_id=sess_row.id, topic_id=topic_id, desired_difficulty=sess_row.current_difficulty)
            needs_refill = first_q is None
        await db.commit()

        return {
            "session": asdict(SessionView(session_uid=sv.session_uid, quiz_uid=sv.quiz_uid, topic_id=str(topic_id) if topic_id else None, current_difficulty=sess_row.current_difficulty, needs_refill=needs_refill)),
            "first_question": asdict(first_q) if first_q else None,
        }

    async def submit_answer(
        self,
        *,
        db: AsyncSession,
        actor_id: UUID,
        actor_role: str,
        session_uid: str,
        question_id: UUID,
        selected_answer: str,
        elapsed_ms: Optional[int],
    ) -> dict[str, Any]:
        """Record an answer and compute next question selection."""
        log.info(f"[SERVICE] submit_answer called - session_uid={session_uid}, question_id={question_id}, actor_id={actor_id}")
        
        # Load session with FOR UPDATE to ensure atomic difficulty/streak update
        # Use NOWAIT to fail fast if lock is held by another transaction (prevents deadlocks)
        log.info(f"[SERVICE] Loading session with FOR UPDATE lock (NOWAIT)...")
        try:
            sess = (
                await db.execute(select(Session).where(Session.session_uid == session_uid).with_for_update(nowait=True))
            ).scalar_one_or_none()
        except Exception as lock_error:
            # If lock is held, wait briefly and retry with standard lock
            log.warning(f"[SERVICE] NOWAIT lock failed, retrying with standard lock: {str(lock_error)}")
            sess = (
                await db.execute(select(Session).where(Session.session_uid == session_uid).with_for_update())
            ).scalar_one_or_none()
        
        if not sess:
            raise AppError("session not found", code=QZ404_SESSION_NOT_FOUND, status=404)
        log.info(f"[SERVICE] Session loaded: id={sess.id}, status={sess.status}")

        # Ownership: actor must be owner unless admin (Pure Clerk)
        is_owner = str(sess.user_id) == str(actor_id)
        is_admin = actor_role == "admin"  # Simple check - all roles from Clerk
        
        if not is_owner and not is_admin:
            raise AppError("forbidden", code="AUTH403_FORBIDDEN", status=403)

        # Ensure question exists and belongs to the same topic (if any)
        q = (await db.execute(select(Question).where(Question.id == question_id))).scalar_one_or_none()
        if not q:
            raise AppError("question not found", code=USR404_NOT_FOUND, status=404)
        if sess.topic_id and q.topic_id != sess.topic_id:
            raise AppError("question not in session topic", code="QZ422_INVALID_QUESTION_TOPIC", status=422)

        # Idempotency: check if already answered
        # Uses the composite index on (session_id, question_id) for fast lookup
        dup = await db.execute(
            select(Attempt.id).where(and_(Attempt.session_id == sess.id, Attempt.question_id == q.id)).limit(1)
        )
        if dup.scalar_one_or_none():
            raise AppError("duplicate answer", code=QZ409_DUPLICATE_ANSWER, status=409)

        # Check if this is the first answer - if so, mark session as "active"
        existing_attempts = await db.execute(
            select(func.count(Attempt.id)).where(Attempt.session_id == sess.id)
        )
        attempt_count = existing_attempts.scalar_one() or 0
        is_first_answer = attempt_count == 0

        # Evaluate correctness
        is_correct = selected_answer == q.correct_answer

        # Update streak/difficulty
        before = int(sess.current_difficulty)
        streak_c = int(sess.streak_correct)
        streak_w = int(sess.streak_wrong)
        mastery = bool(sess.mastery_reached)

        if is_correct:
            streak_c += 1
            streak_w = 0
            if streak_c >= 3 and before < 5:
                before = min(5, before + 1)
                streak_c = 0
            # mastery if at difficulty 5 and >=10 consecutive correct at 5
            if int(sess.current_difficulty) == 5 and before == 5 and streak_c >= 10:
                mastery = True
        else:
            streak_w += 1
            streak_c = 0
            if streak_w >= 3 and before > 1:
                before = max(1, before - 1)
                streak_w = 0

        new_difficulty = before

        # Insert attempt - use regular SQLAlchemy insert for better compatibility
        # The duplicate check above should prevent duplicates, so this should be fast
        log.info(f"[SERVICE] About to INSERT attempt - session_id={sess.id}, question_id={q.id}, is_correct={is_correct}")
        log.info(f"[SERVICE] Attempting database INSERT (this is where timeout might occur)...")
        
        # Try using regular insert instead of pg_insert to see if it's faster
        # Also flush before the INSERT to ensure session state is clean
        try:
            # Flush any pending changes to ensure clean state
            await db.flush()
            
            # Use pg_insert with explicit RETURNING to ensure it completes
            # The index should make this fast, but if it's still slow, there may be lock contention
            stmt = pg_insert(Attempt).values(
                session_id=sess.id,
                question_id=q.id,
                selected_answer=selected_answer,
                is_correct=is_correct,
                elapsed_ms=elapsed_ms,
            ).returning(Attempt.id)
            
            result = await db.execute(stmt)
            inserted_id = result.scalar_one()
            log.info(f"[SERVICE] INSERT attempt completed successfully - inserted_id={inserted_id}")
        except Exception as insert_error:
            error_type = type(insert_error).__name__
            error_msg = str(insert_error)
            log.error(f"[SERVICE] INSERT failed: {error_type}: {error_msg}")
            
            # Check if it's a unique constraint violation (duplicate)
            if "unique constraint" in error_msg.lower() or "duplicate key" in error_msg.lower() or "uq_attempts_session_question" in error_msg:
                raise AppError("duplicate answer", code=QZ409_DUPLICATE_ANSWER, status=409)
            
            # If it's a timeout, provide more context
            if "timeout" in error_msg.lower() or error_type == "TimeoutError":
                log.error(f"[SERVICE] INSERT timed out - this may indicate database lock contention or missing indexes")
                log.error(f"[SERVICE] Suggestion: Run migration 'f20bbc32f718' to add composite index on attempts table")
                # Check if there are any long-running transactions
                log.error(f"[SERVICE] This could also indicate a deadlock or long-running transaction holding locks")
                raise AppError(
                    "Database operation timed out. This may be due to missing database indexes. Please contact support.",
                    code="DB_TIMEOUT",
                    status=504
                )
            raise

        # Update session - mark as "active" if this is the first answer
        log.info(f"[SERVICE] Updating session with new difficulty={new_difficulty}, streaks=({streak_c}, {streak_w})")
        update_values = {
            "current_difficulty": new_difficulty,
            "streak_correct": streak_c,
            "streak_wrong": streak_w,
            "mastery_reached": mastery
        }
        if is_first_answer:
            update_values["status"] = "active"
        
        await db.execute(
            sa.update(Session)
            .where(Session.id == sess.id)
            .values(**update_values)
        )
        log.info(f"[SERVICE] Session update completed")

        # Emit event
        await db.execute(
            pg_insert(Event).values(
                session_id=sess.id,
                user_id=actor_id,
                event_type="ATTEMPT_RECORDED",
                payload={
                    "question_id": str(q.id),
                    "is_correct": is_correct,
                    "difficulty_before": int(sess.current_difficulty),
                    "difficulty_after": new_difficulty,
                    "elapsed_ms": elapsed_ms,
                },
            )
        )

        # Next question selection (same transaction)
        log.info(f"[SERVICE] Selecting next question for difficulty={new_difficulty}")
        next_q: Optional[QuestionView] = None
        needs_refill = False
        if sess.topic_id:
            next_q = await _select_next_question(
                db,
                session_id=sess.id,
                topic_id=sess.topic_id,
                desired_difficulty=new_difficulty,
            )
            needs_refill = next_q is None
            log.info(f"[SERVICE] Next question selected: {next_q.id if next_q else None}, needs_refill={needs_refill}")

        log.info(f"[SERVICE] About to commit transaction...")
        await db.commit()
        log.info(f"[SERVICE] Transaction committed successfully")

        log.info(
            "attempt_recorded",
            extra={
                "request_id": None,  # router will add; here we keep structure
                "user_id": str(actor_id),
                "role": actor_role,
                "topic_id": str(sess.topic_id) if sess.topic_id else None,
                "session_id": session_uid,
                "question_id": str(q.id),
                "is_correct": is_correct,
                "difficulty_before": int(sess.current_difficulty),
                "difficulty_after": new_difficulty,
                "needs_refill": needs_refill,
            },
        )

        return {
            "is_correct": is_correct,
            "next_question": asdict(next_q) if next_q else None,
            "needs_refill": needs_refill,
        }

    async def summarize_session(self, *, db: AsyncSession, actor_id: UUID, actor_role: str, session_uid: str) -> dict[str, Any]:
        """Summarize a completed session (score, per-difficulty accuracy)."""
        sess = (await db.execute(select(Session).where(Session.session_uid == session_uid))).scalar_one_or_none()
        if not sess:
            raise AppError("session not found", code=QZ404_SESSION_NOT_FOUND, status=404)
        # Ownership: actor must be owner unless admin (Pure Clerk)
        is_owner = str(sess.user_id) == str(actor_id)
        is_admin = actor_role == "admin"  # Simple check - all roles from Clerk
        
        if not is_owner and not is_admin:
            raise AppError("forbidden", code="AUTH403_FORBIDDEN", status=403)

        # Aggregate totals and per-difficulty accuracy
        j = (
            select(
                Question.difficulty.label("difficulty"),
                func.count(Attempt.id).label("count"),
                func.sum(func.cast(Attempt.is_correct, sa.Integer)).label("correct"),
            )
            .join(Question, Question.id == Attempt.question_id)
            .where(Attempt.session_id == sess.id)
            .group_by(Question.difficulty)
            .order_by(Question.difficulty)
        )
        res = await db.execute(j)
        rows = res.all()
        totals = sum(int(r.count) for r in rows) if rows else 0
        correct = sum(int(r.correct or 0) for r in rows) if rows else 0
        per_diff = [
            {"difficulty": int(r.difficulty), "attempts": int(r.count), "correct": int(r.correct or 0), "accuracy": (int(r.correct or 0) / int(r.count)) if int(r.count) else 0.0}
            for r in rows
        ]

        accuracy_value = (correct / totals) if totals else 0.0
        
        # Populate quiz_summaries table for efficient history queries
        # Only create summary if there's at least one attempt (valid quiz)
        if sess.user_id and totals > 0:  # Only populate if user_id exists and there are attempts
            try:
                await upsert_quiz_summary(
                    db=db,
                    session_id=sess.id,
                    user_id=sess.user_id,
                    topic_id=sess.topic_id,
                    total_attempts=totals,
                    correct_answers=correct,
                    accuracy=accuracy_value,
                    final_difficulty=int(sess.current_difficulty),
                    mastery_reached=bool(sess.mastery_reached),
                    ended_at=sess.ended_at,
                )
                await db.commit()  # Commit the summary insert
            except Exception as e:
                log.warning(f"Failed to upsert quiz summary for session {session_uid}: {e}")
                # Don't fail the request if summary upsert fails
                await db.rollback()

        return {
            "session_uid": session_uid,
            "topic_id": str(sess.topic_id) if sess.topic_id else None,
            "current_difficulty": int(sess.current_difficulty),
            "mastery_reached": bool(sess.mastery_reached),
            "attempts": totals,
            "correct": correct,
            "accuracy": accuracy_value,
            "by_difficulty": per_diff,
        }
