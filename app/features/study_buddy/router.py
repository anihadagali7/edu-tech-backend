"""FastAPI router wiring for Study Buddy session management and SSE streaming."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.auth.middleware import clerk_auth_dependency
from app.db.base import get_session
from app.features.study_buddy import ENABLE_STUDY_BUDDY
from app.features.study_buddy import service
from app.features.study_buddy.repositories import StudyBuddyRepository
from app.features.study_buddy.schemas import (
    StudyMessageRequest,
    StudyMessageResponse,
    StartStudySessionRequest,
)
from app.features.study_buddy.sse import _study_buddy_event_generator

router = APIRouter(prefix="/study-buddy", tags=["study-buddy"])


def _require_feature_enabled() -> None:
    if not ENABLE_STUDY_BUDDY:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Study Buddy feature is disabled")


def _principal_user_id(principal: Dict[str, Any]) -> str:
    return str(principal.get("clerk_user_id") or principal.get("id"))


@router.post("/sessions", response_model=StudyMessageResponse, status_code=status.HTTP_201_CREATED)
async def start_study_session(
    payload: StartStudySessionRequest,
    user=Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> StudyMessageResponse:
    """Start a new study session for the authenticated user.
    
    After creating a session, connect to the SSE endpoint to stream responses:
    GET /sse/study-buddy/{session_id}
    """

    _require_feature_enabled()
    user_id = _principal_user_id(user)
    repository = StudyBuddyRepository(db)
    response = await service.start_session(user_id=user_id, payload=payload, repository=repository)
    await db.commit()
    return response


@router.get("/sessions/{session_id}/stream")
async def stream_session_response(
    session_id: str,
    user=Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> EventSourceResponse:
    """Server-Sent Events endpoint for streaming AI tutor responses in real-time.
    
    Usage:
    1. Create a session with POST /study-buddy/sessions
    2. Connect to this endpoint: GET /study-buddy/sessions/{session_id}/stream
    3. Post messages via POST /study-buddy/sessions/{session_id}/messages
    4. Responses stream in real-time as SSE events
    
    Event types:
    - hint_meta: Hint level and metadata
    - token: Streaming text token
    - done: Message complete
    """

    _require_feature_enabled()
    user_id = _principal_user_id(user)
    repository = StudyBuddyRepository(db)
    
    return EventSourceResponse(
        _study_buddy_event_generator(session_id, user_id, repository),
        media_type="text/event-stream",
    )


@router.post("/sessions/{session_id}/messages", response_model=StudyMessageResponse, status_code=status.HTTP_202_ACCEPTED)
async def post_study_message(
    session_id: str,
    payload: StudyMessageRequest,
    user=Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> StudyMessageResponse:
    """Post a message to the study session.
    
    This endpoint queues the message for processing. The response will be streamed
    via the SSE endpoint GET /study-buddy/sessions/{session_id}/stream
    
    The client should already be connected to the SSE endpoint before posting messages.
    """

    _require_feature_enabled()
    user_id = _principal_user_id(user)
    repository = StudyBuddyRepository(db)
    response = await service.post_message(user_id=user_id, session_id=session_id, message=payload, repository=repository)
    await db.commit()
    return response

