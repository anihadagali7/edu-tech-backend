# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""Server-sent events streaming utilities for Study Buddy tutor responses."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import clerk_auth_dependency
from app.db.base import get_session
from app.features.study_buddy import ENABLE_STUDY_BUDDY
from app.features.study_buddy.repositories import StudyBuddyRepository
from app.features.study_buddy.schemas import ContextSnapshot, StudyMessageRequest
from app.features.study_buddy.service import (
    StreamEvent,
    dequeue_pending_message,
    generate_tutor_reply,
    get_session as get_study_session,
)
from app.features.study_buddy.retrieval import resolve_context
from app.utils.errors import AppError

router = APIRouter(prefix="/sse", tags=["sse"])


def _require_feature_enabled() -> None:
    if not ENABLE_STUDY_BUDDY:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Study Buddy feature is disabled")


def _principal_user_id(principal: Dict[str, Any]) -> str:
    return str(principal.get("clerk_user_id") or principal.get("id"))


def _format_event(event: StreamEvent) -> str:
    return event.to_sse_payload()


async def _study_buddy_event_generator(session_id: str, user_id: str, repository: StudyBuddyRepository | None) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted lines for a tutor reply, including hint metadata and completion signals."""

    _require_feature_enabled()
    log = __import__("logging").getLogger("study_buddy.sse")
    log.info(f"SSE generator started for session {session_id}")
    
    state = await get_study_session(user_id=user_id, session_id=session_id, repository=repository)
    log.info(f"Got session state, mode={state.mode}")
    
    _, pending_message = await dequeue_pending_message(session_id)
    message = pending_message or StudyMessageRequest(message="Let's get started!", mode=state.mode, context=state.context)
    log.info(f"Got message: {message.message[:50]}...")

    yield "retry: 5000\n\n"
    log.info("Yielded retry line")

    resolved_context = await resolve_context(
        repository=repository,
        session_id=session_id,
        explicit_ctx=message.context or state.context,
    )
    log.info(f"Resolved context")

    try:
        log.info("Starting to generate tutor reply...")
        event_count = 0
        async for event in generate_tutor_reply(
            repository=repository,
            session_id=session_id,
            message=message,
            context=resolved_context,
        ):
            event_count += 1
            log.info(f"Yielding event {event_count}: {event.event}")
            yield _format_event(event)
        log.info(f"Finished generating, total events: {event_count}")
    except AppError as exc:
        log.error(f"AppError during generation: {exc.code} - {exc.message}")
        error_payload = json.dumps({"code": exc.code, "message": exc.message})
        yield f"event: error\ndata: {error_payload}\n\n"
        return
    except Exception as exc:  # pragma: no cover - defensive guard
        log.error(f"Exception during generation: {exc}", exc_info=True)
        error_payload = json.dumps({"code": "internal_error", "message": str(exc)})
        yield f"event: error\ndata: {error_payload}\n\n"
        return

    heartbeat = json.dumps({"session_id": session_id, "timestamp": int(time.time())})
    yield f"event: heartbeat\ndata: {heartbeat}\n\n"
    log.info("SSE generator completed")


@router.get("/study-buddy/{session_id}")
async def study_buddy_stream(
    session_id: str,
    user=Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Expose a StreamingResponse endpoint that proxies tutor-generated SSE events."""

    _require_feature_enabled()
    user_id = _principal_user_id(user)
    repository = StudyBuddyRepository(db)

    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream; charset=utf-8",
        "X-Accel-Buffering": "no",
    }

    return StreamingResponse(
        _study_buddy_event_generator(session_id=session_id, user_id=user_id, repository=repository),
        status_code=status.HTTP_200_OK,
        headers=headers,
        media_type="text/event-stream",
    )
