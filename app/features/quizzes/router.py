"""Quiz lifecycle routes.

Maps to Section 5.2 of the design: Quiz start, answering, and summary endpoints.

Routes:
  - POST /quizzes/start
  - POST /quizzes/{session_uid}/answer
  - GET  /quizzes/{session_uid}/summary

RBAC:
  - Auth required for all routes (users & admins).
  - Ownership enforced by the service (admin may inspect any session).

Notes:
  - SSE publishing of attempt/next-question is wired via in-memory broadcaster.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import clerk_auth_dependency
from app.auth.schemas import Envelope
from app.db.base import get_session
from app.db.repositories import list_user_sessions, get_session_details_with_attempts
from app.features.quizzes.service import AdaptiveService
from app.features.quizzes.sse import publish_session_event
from app.utils.errors import AppError, QZ404_SESSION_NOT_FOUND

router = APIRouter(prefix="/quizzes", tags=["quizzes"], dependencies=[Depends(clerk_auth_dependency)])
log = logging.getLogger("quizzes")


class StartQuizRequest(BaseModel):
    """Request payload to start a quiz session."""
    topic_id: Optional[str] = Field(default=None, description="Topic UUID")
    topic_name: Optional[str] = Field(default=None, description="Topic name to ensure placeholder + pending job if missing")
    difficulty_hint: Optional[int] = Field(default=None, ge=1, le=5, description="Initial difficulty (clamped 1..5)")


class AnswerRequest(BaseModel):
    """Submit an answer within a session."""
    question_id: str
    selected_answer: str
    elapsed_ms: int | None = None


_service = AdaptiveService()


@router.post("/start", response_model=Envelope, status_code=status.HTTP_200_OK)
async def start_quiz(
    req: StartQuizRequest,
    request: Request,
    principal: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Start a new quiz session.

    Ownership: session belongs to the authenticated user (principal['id']).
    """
    # principal['id'] is now always a string UUID from auth middleware
    user_id = UUID(principal["id"])
    topic_id_uuid: UUID | None = UUID(req.topic_id) if req.topic_id else None

    result = await _service.start_quiz(
        db=db,
        actor_id=user_id,
        topic_id=topic_id_uuid,
        topic_name=req.topic_name,
        difficulty_hint=req.difficulty_hint,
    )

    # Observability
    log.info(
        "quiz_start",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "user_id": principal["id"],
            "role": principal.get("role"),
            "topic_id": result["session"]["topic_id"],
            "session_id": result["session"]["session_uid"],
            "difficulty": result["session"]["current_difficulty"],
            "needs_refill": result["session"]["needs_refill"],
        },
    )

    # Optionally notify clients that session started (lightweight)
    await publish_session_event(
        result["session"]["session_uid"],
        "started",
        {
            "session": result["session"],
            "first_question": result.get("first_question"),
        },
    )

    return Envelope(data=result)


@router.post(
    "/{session_uid}/answer",
    response_model=Envelope,
    status_code=status.HTTP_200_OK,
)
async def answer(
    req: AnswerRequest,
    request: Request,
    session_uid: str = Path(..., description="Session UID / quiz_id"),
    principal: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Record an answer and return correctness + optional next question."""
    # principal['id'] is now always a string UUID from auth middleware
    user_id = UUID(principal["id"])
    role = str(principal.get("role", "user"))
    question_id = UUID(req.question_id)

    result = await _service.submit_answer(
        db=db,
        actor_id=user_id,
        actor_role=role,
        session_uid=session_uid,
        question_id=question_id,
        selected_answer=req.selected_answer,
        elapsed_ms=req.elapsed_ms,
    )

    # Observability
    log.info(
        "quiz_answer",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "user_id": principal["id"],
            "role": role,
            "session_id": session_uid,
            "question_id": req.question_id,
            "is_correct": result["is_correct"],
            "next_question_id": (result["next_question"]["id"] if result.get("next_question") else None),
            "needs_refill": result.get("needs_refill"),
        },
    )

    # Publish SSE updates
    await publish_session_event(
        session_uid,
        "answer",
        {"question_id": req.question_id, "is_correct": result["is_correct"], "elapsed_ms": req.elapsed_ms},
    )
    if result.get("next_question"):
        await publish_session_event(session_uid, "question", result["next_question"])
    elif result.get("needs_refill"):
        await publish_session_event(session_uid, "needs_refill", {"session_id": session_uid})

    return Envelope(data=result)


@router.get(
    "/{session_uid}/summary",
    response_model=Envelope,
    status_code=status.HTTP_200_OK,
)
async def summary(
    request: Request,
    session_uid: str = Path(..., description="Session UID / quiz_id"),
    principal: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Return session summary."""
    # principal['id'] is now always a string UUID from auth middleware
    user_id = UUID(principal["id"])
    role = str(principal.get("role", "user"))

    result = await _service.summarize_session(db=db, actor_id=user_id, actor_role=role, session_uid=session_uid)
    if not result:
        raise AppError("session not found", code=QZ404_SESSION_NOT_FOUND, status=404)

    log.info(
        "quiz_summary",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "user_id": principal["id"],
            "role": role,
            "session_id": session_uid,
            "attempts": result.get("attempts"),
            "correct": result.get("correct"),
            "accuracy": result.get("accuracy"),
            "current_difficulty": result.get("current_difficulty"),
            "mastery_reached": result.get("mastery_reached"),
        },
    )

    # Optional: push a summary event for connected clients
    await publish_session_event(session_uid, "summary", result)

    return Envelope(data=result)


@router.get("/sessions", response_model=Envelope, status_code=status.HTTP_200_OK)
async def list_sessions(
    request: Request,
    topic_id: Optional[str] = Query(default=None, description="Filter by topic UUID"),
    status: Optional[str] = Query(default="completed", description="Filter by status (completed, active, paused)"),
    from_date: Optional[str] = Query(default=None, description="Filter by start date (ISO format)"),
    to_date: Optional[str] = Query(default=None, description="Filter by end date (ISO format)"),
    min_accuracy: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="Minimum accuracy (0.0-1.0)"),
    limit: int = Query(default=50, ge=1, le=200, description="Number of results per page"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    principal: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """List quiz sessions for the authenticated user with optional filters."""
    user_id = UUID(principal["id"])
    
    # Parse dates if provided
    from_date_parsed: Optional[datetime] = None
    to_date_parsed: Optional[datetime] = None
    
    if from_date:
        try:
            from_date_parsed = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
        except ValueError:
            raise AppError("Invalid from_date format. Use ISO format (e.g., 2025-01-15T00:00:00Z)", code="QZ400_INVALID_DATE", status=400)
    
    if to_date:
        try:
            to_date_parsed = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
        except ValueError:
            raise AppError("Invalid to_date format. Use ISO format (e.g., 2025-01-15T00:00:00Z)", code="QZ400_INVALID_DATE", status=400)
    
    # Parse topic_id if provided
    topic_id_parsed: Optional[UUID] = None
    if topic_id:
        try:
            topic_id_parsed = UUID(topic_id)
        except ValueError:
            raise AppError("Invalid topic_id format", code="QZ400_INVALID_TOPIC_ID", status=400)
    
    result = await list_user_sessions(
        db=db,
        user_id=user_id,
        topic_id=topic_id_parsed,
        status=status,
        from_date=from_date_parsed,
        to_date=to_date_parsed,
        min_accuracy=min_accuracy,
        limit=limit,
        offset=offset,
    )
    
    log.info(
        "quiz_sessions_list",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "user_id": principal["id"],
            "topic_id": topic_id,
            "status": status,
            "count": result.get("total", 0),
        },
    )
    
    return Envelope(data=result)


@router.get("/{session_uid}/details", response_model=Envelope, status_code=status.HTTP_200_OK)
async def session_details(
    request: Request,
    session_uid: str = Path(..., description="Session UID"),
    principal: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Get detailed session history with all attempts, questions, and answers for review."""
    user_id = UUID(principal["id"])
    role = str(principal.get("role", "user"))
    
    result = await get_session_details_with_attempts(
        db=db,
        session_uid=session_uid,
        user_id=user_id,
    )
    
    if not result:
        # Check if session exists but user doesn't have access (unless admin)
        from app.db.models import Session
        from sqlalchemy import select
        
        session_check = await db.execute(
            select(Session).where(Session.session_uid == session_uid)
        )
        sess = session_check.scalar_one_or_none()
        
        if not sess:
            raise AppError("session not found", code=QZ404_SESSION_NOT_FOUND, status=404)
        
        # If session exists but not accessible, check if user is admin
        if role != "admin":
            raise AppError("forbidden", code="AUTH403_FORBIDDEN", status=403)
        
        # Admin can access any session - fetch it again without ownership check
        # For now, we'll just return 404 if not found, but we could add admin logic here
    
    log.info(
        "quiz_session_details",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "user_id": principal["id"],
            "role": role,
            "session_id": session_uid,
            "attempts_count": len(result.get("attempts", [])) if result else 0,
        },
    )
    
    return Envelope(data=result)