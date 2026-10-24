"""Complete SSE implementation for adaptive quiz sessions.

Provides real-time quiz experience with:
- Automatic question delivery based on adaptive difficulty
- Real-time answer feedback and explanations
- Dynamic difficulty adjustment
- Live progress updates
- Comprehensive quiz analytics
- Session completion with detailed summary

Path:
  - GET /sse/quiz/start?topic_id=<uuid>   # Start SSE quiz session (creates new session)
  - POST /sse/quiz/{session_uid}/answer   # Submit answer via SSE
  - GET /sse/quiz/{session_uid}/summary   # Get final summary

IMPORTANT WORKFLOW:
1. Frontend connects to GET /sse/quiz/start?topic_id=<uuid>
2. Server creates a new session and sends 'session_started' event with session_uid
3. Frontend stores that session_uid (in component state/context)
4. Frontend uses session_uid for all subsequent answer submissions
5. All subsequent events are automatically pushed via the SSE connection
"""

from __future__ import annotations

import asyncio
import json
import time
import logging
from typing import AsyncIterator, Dict, Set, Optional, Any
from uuid import UUID

from fastapi import APIRouter, Path, Request, Depends, HTTPException, status, Body, Query
from starlette.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.auth.middleware import clerk_auth_dependency
from app.auth.schemas import Envelope
from app.db.base import get_session
from app.features.quizzes.service import AdaptiveService
from app.db.models import Session as QuizSession, Topic, Question, Attempt, Event, QuizSummary
from sqlalchemy import select, and_, func, desc, update, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

router = APIRouter(prefix="/sse", tags=["sse"])
log = logging.getLogger("quiz.sse")


# ---------------- Enhanced Quiz Session Management ----------------

class QuizSessionManager:
    """Manages active quiz sessions with adaptive difficulty and progress tracking."""
    
    def __init__(self, max_queue_size: int = 50):
        self._subscribers: Dict[str, Set[asyncio.Queue[bytes]]] = {}
        self._lock = asyncio.Lock()
        self._max = max_queue_size
        self._service = AdaptiveService()
    
    async def start_session(self, user_id: UUID, topic_id: Optional[UUID], db: AsyncSession) -> Dict[str, Any]:
        """Initialize a new quiz session or resume a paused session.
        
        First checks if there's a paused session for this user/topic.
        If found, resumes it. Otherwise, creates a new session.
        """
        # Check for existing paused session for this user and topic
        if topic_id:
            paused_session_query = select(QuizSession).where(
                and_(
                    QuizSession.user_id == user_id,
                    QuizSession.topic_id == topic_id,
                    QuizSession.status == "paused"
                )
            ).order_by(QuizSession.started_at.desc()).limit(1)
            
            paused_result = await db.execute(paused_session_query)
            paused_session = paused_result.scalar_one_or_none()
            
            if paused_session:
                # Resume paused session
                # Mark as active again
                await db.execute(
                    update(QuizSession)
                    .where(QuizSession.id == paused_session.id)
                    .values(status="active")
                )
                await db.commit()
                
                # Get the next question (where they left off)
                from app.features.quizzes.service import _select_next_question
                next_question = None
                needs_refill = False
                
                if paused_session.topic_id:
                    next_question_obj = await _select_next_question(
                        db,
                        session_id=paused_session.id,
                        topic_id=paused_session.topic_id,
                        desired_difficulty=paused_session.current_difficulty
                    )
                    if next_question_obj:
                        next_question = {
                            'id': next_question_obj.id,
                            'body': next_question_obj.body,
                            'choices': next_question_obj.choices,
                            'difficulty': next_question_obj.difficulty
                        }
                    else:
                        needs_refill = True
                
                log.info(f"Resumed paused session {paused_session.session_uid} for user {user_id}")
                
                return {
                    'session_uid': paused_session.session_uid,
                    'status': 'resumed',
                    'current_difficulty': paused_session.current_difficulty,
                    'needs_refill': needs_refill,
                    'first_question': next_question
                }
        
        # No paused session found, create new session
        # Use the AdaptiveService to create the session (ensures consistency with standard API)
        result = await self._service.start_quiz(
            db=db,
            actor_id=user_id,
            topic_id=topic_id,
            topic_name=None,
            difficulty_hint=3
        )
        
        # Extract session info and first question from service result
        session_info = result['session']
        first_question = result.get('first_question')
        
        return {
            'session_uid': session_info['session_uid'],
            'status': 'started',
            'current_difficulty': session_info['current_difficulty'],
            'needs_refill': session_info.get('needs_refill', False),
            'first_question': first_question
        }
    
    async def submit_answer(self, session_uid: str, question_id: str, selected_answer: str, 
                           elapsed_ms: Optional[int], user_id: UUID, user_role: str, db: AsyncSession) -> Dict[str, Any]:
        """Process answer submission using the robust service logic."""
        log.info(f"[SESSION_MANAGER] submit_answer called - session_uid={session_uid}, question_id={question_id}")
        
        # Validate and convert question_id to UUID
        try:
            question_uuid = UUID(question_id)
            log.info(f"[SESSION_MANAGER] question_id converted to UUID: {question_uuid}")
        except (ValueError, TypeError) as e:
            log.error(f"Invalid question_id format: {question_id}")
            raise HTTPException(status_code=400, detail=f"Invalid question ID format: {question_id}")
        
        # Use the AdaptiveService to submit the answer (ensures consistency with standard API)
        log.info(f"[SESSION_MANAGER] About to call service.submit_answer")
        result = await self._service.submit_answer(
            db=db,
            actor_id=user_id,
            actor_role=user_role,  # Use the actual user role (could be org role)
            session_uid=session_uid,
            question_id=question_uuid,
            selected_answer=selected_answer,
            elapsed_ms=elapsed_ms
        )
        
        # Get updated session info from database
        session_query = select(QuizSession).where(QuizSession.session_uid == session_uid)
        session_result = await db.execute(session_query)
        session = session_result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get question details for explanation
        question_query = select(Question).where(Question.id == question_uuid)
        question_result = await db.execute(question_query)
        question = question_result.scalar_one_or_none()
        
        # Check if session should end (mastery reached or too many questions)
        attempts_count = await db.execute(
            select(func.count(Attempt.id)).where(Attempt.session_id == session.id)
        )
        total_attempts = attempts_count.scalar()
        
        session_ended = session.mastery_reached or total_attempts >= 20
        
        if session_ended:
            # Mark session as completed
            await db.execute(
                update(QuizSession).where(QuizSession.id == session.id).values(
                    status='completed',
                    ended_at=func.now()
                )
            )
            await db.commit()
        
        # Build detailed explanation response
        explanation_response = {}
        if question and question.explanations:
            explanations = question.explanations
            
            # Always include the correct answer explanation
            explanation_response['correct_explanation'] = explanations.get('correct', '')
            
            # If answer was wrong, include why the selected answer is wrong
            if not result['is_correct'] and 'distractors' in explanations:
                distractors = explanations.get('distractors', {})
                selected_explanation = distractors.get(selected_answer, '')
                explanation_response['selected_explanation'] = selected_explanation
                explanation_response['why_wrong'] = selected_explanation  # Alias for clarity
            
            # Include all choices for context (frontend might want to show all explanations)
            explanation_response['all_explanations'] = explanations
        
        return {
            'is_correct': result['is_correct'],
            'correct_answer': question.correct_answer if question else selected_answer,
            'selected_answer': selected_answer,  # Echo back what user selected
            'explanation': explanation_response,
            'next_question': result.get('next_question'),
            'session_stats': {
                'questions_answered': total_attempts,
                'current_difficulty': session.current_difficulty,
                'streak_correct': session.streak_correct,
                'streak_wrong': session.streak_wrong,
                'mastery_reached': session.mastery_reached
            },
            'session_ended': session_ended,
            'needs_refill': result.get('needs_refill', False)
        }
    
    # The adaptive logic is now handled by the AdaptiveService, so these methods are no longer needed
    
    async def get_session_summary(self, session_uid: str, user_id: UUID, user_role: str, db: AsyncSession) -> Dict[str, Any]:
        """Generate comprehensive quiz summary using the service logic."""
        # Use the AdaptiveService to get the basic summary
        basic_summary = await self._service.summarize_session(
            db=db,
            actor_id=user_id,
            actor_role=user_role,  # Use the actual user role (could be org role)
            session_uid=session_uid
        )
        
        # Get additional analytics from the database
        session_query = select(QuizSession).where(QuizSession.session_uid == session_uid)
        session_result = await db.execute(session_query)
        session = session_result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get detailed attempt history with questions
        attempts_query = select(
            Attempt.question_id,
            Attempt.selected_answer,
            Attempt.is_correct,
            Attempt.elapsed_ms,
            Question.body,
            Question.choices,
            Question.correct_answer,
            Question.explanations,
            Question.difficulty
        ).join(Question, Question.id == Attempt.question_id).where(
            Attempt.session_id == session.id
        ).order_by(Attempt.created_at)
        
        attempts_result = await db.execute(attempts_query)
        attempts = attempts_result.all()
        
        # Build question history
        question_history = []
        total_time_ms = 0
        question_times = []
        
        for attempt in attempts:
            question_history.append({
                'question_id': str(attempt.question_id),
                'question_body': attempt.body,
                'selected_answer': attempt.selected_answer,
                'correct_answer': attempt.correct_answer,
                'is_correct': attempt.is_correct,
                'difficulty': attempt.difficulty,
                'elapsed_ms': attempt.elapsed_ms,
                'explanations': attempt.explanations
            })
            
            if attempt.elapsed_ms:
                question_times.append(attempt.elapsed_ms)
                total_time_ms += attempt.elapsed_ms
        
        # Calculate additional analytics
        avg_time = sum(question_times) / max(1, len(question_times)) if question_times else 0
        
        # Identify strengths and weaknesses from difficulty breakdown
        strengths = []
        weaknesses = []
        
        for diff_data in basic_summary['by_difficulty']:
            difficulty = diff_data['difficulty']
            accuracy = diff_data['accuracy']
            
            if accuracy >= 0.8:
                strengths.append(f"Level {difficulty} questions")
            elif accuracy < 0.6:
                weaknesses.append(f"Level {difficulty} questions")
        
        # Performance trends (last 5 questions)
        recent_accuracy = 0
        if len(question_history) >= 5:
            recent_questions = question_history[-5:]
            recent_correct = sum(1 for q in recent_questions if q['is_correct'])
            recent_accuracy = recent_correct / len(recent_questions)
        
        # Improvement areas and recommendations  
        improvement_areas = []
        if avg_time > 30000:  # 30 seconds
            improvement_areas.append("Speed up response time")
        if basic_summary['accuracy'] < 0.7:
            improvement_areas.append("Focus on understanding core concepts")
        if basic_summary['current_difficulty'] < 3:
            improvement_areas.append("Build confidence with practice")
        
        recommendations = []
        if basic_summary['mastery_reached']:
            recommendations.append("Excellent work! You've mastered this topic.")
            recommendations.append("Try more advanced topics to continue learning.")
        else:
            if basic_summary['accuracy'] < 0.6:
                recommendations.append("Review the fundamentals before attempting harder questions.")
            elif basic_summary['accuracy'] < 0.8:
                recommendations.append("You're making good progress. Keep practicing!")
            else:
                recommendations.append("Great accuracy! Focus on challenging yourself with harder questions.")
        
        return {
            'session_summary': {
                'session_uid': session_uid,
                'status': 'completed',
                'mastery_reached': basic_summary['mastery_reached'],
                'duration_ms': total_time_ms
            },
            'performance': {
                'questions_answered': basic_summary['attempts'],
                'correct_answers': basic_summary['correct'],
                'accuracy': round(basic_summary['accuracy'], 3),
                'avg_time_ms': round(avg_time) if question_times else 0,
                'final_difficulty': basic_summary['current_difficulty'],
            },
            'analytics': {
                'difficulty_breakdown': basic_summary['by_difficulty'],
                'recent_performance': round(recent_accuracy, 3),
                'time_per_question': question_times
            },
            'insights': {
                'strengths': strengths,
                'weaknesses': weaknesses,
                'improvement_areas': improvement_areas,
                'recommendations': recommendations
            },
            'question_history': question_history
        }
    
    async def subscribe(self, session_uid: str) -> asyncio.Queue[bytes]:
        """Subscribe to session events."""
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=self._max)
        async with self._lock:
            self._subscribers.setdefault(session_uid, set()).add(q)
        return q
    
    async def unsubscribe(self, session_uid: str, q: asyncio.Queue[bytes]) -> None:
        """Unsubscribe from session events."""
        async with self._lock:
            qs = self._subscribers.get(session_uid)
            if qs and q in qs:
                qs.remove(q)
                if not qs:
                    self._subscribers.pop(session_uid, None)
    
    async def publish(self, session_uid: str, event: str, data: dict) -> None:
        """Publish event to all subscribers."""
        payload = f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'), default=str)}\n\n".encode("utf-8")
        async with self._lock:
            for q in self._subscribers.get(session_uid, set()).copy():
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    try:
                        _ = q.get_nowait()
                        q.put_nowait(payload)
                    except (asyncio.QueueEmpty, asyncio.QueueFull):
                        pass

_session_manager = QuizSessionManager()


# ---------------- Request/Response Schemas ----------------

class StartQuizSSERequest(BaseModel):
    """Request to start SSE-based quiz session."""
    topic_id: str = Field(..., description="Topic UUID")
    difficulty_hint: Optional[int] = Field(default=3, ge=1, le=5, description="Initial difficulty")


class AnswerSSERequest(BaseModel):
    """Submit answer via SSE."""
    question_id: str = Field(..., description="Question UUID")
    selected_answer: str = Field(..., description="Selected answer (A, B, C, D)")
    elapsed_ms: Optional[int] = Field(default=None, description="Time taken in milliseconds")


# ---------------- Public Helper Functions ----------------

async def publish_session_event(session_uid: str, event: str, data: dict) -> None:
    """Public helper to publish an SSE message for a session."""
    await _session_manager.publish(session_uid, event, data)


# ---------------- SSE Endpoints ----------------

async def _quiz_sse_stream(request: Request, user_id: UUID, 
                          topic_id: str, db: AsyncSession) -> AsyncIterator[bytes]:
    """Main SSE stream for adaptive quiz sessions."""
    
    # CRITICAL FIX: Create session FIRST, then subscribe to the actual DB-generated session_uid
    session_info = await _session_manager.start_session(
        user_id=user_id,
        topic_id=UUID(topic_id),
        db=db
    )
    
    # Get the REAL session_uid generated by the database
    actual_session_uid = session_info['session_uid']
    
    try:
        # Subscribe to session events using the ACTUAL session_uid
        q = await _session_manager.subscribe(actual_session_uid)
        
        # Send initial session info with the REAL session_uid
        yield f"event: session_started\ndata: {json.dumps(session_info, default=str)}\n\n".encode("utf-8")
        
        # Send first question if available
        if session_info.get('first_question'):
            yield f"event: question\ndata: {json.dumps(session_info['first_question'], default=str)}\n\n".encode("utf-8")
        
        # Send heartbeats and handle events
        last_heartbeat = time.monotonic()
        heartbeat_interval = 30  # 30 seconds
        
        while True:
            try:
                # Check for events with timeout
                msg = await asyncio.wait_for(q.get(), timeout=100.0)
                yield msg
            except asyncio.TimeoutError:
                pass
            
            # Send heartbeat
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_interval:
                heartbeat_data = {
                    "session_uid": actual_session_uid,
                    "timestamp": int(time.time()),
                    "status": "active"
                }
                yield f"event: heartbeat\ndata: {json.dumps(heartbeat_data)}\n\n".encode("utf-8")
                last_heartbeat = now
            
            # Check if client disconnected
            if await request.is_disconnected():
                log.info(f"Client disconnected from quiz session {actual_session_uid}")
                break
            
            await asyncio.sleep(0.1)
            
    except Exception as e:
        log.error(f"Error in quiz SSE stream: {str(e)}")
        error_data = {"error": str(e), "session_uid": actual_session_uid}
        yield f"event: error\ndata: {json.dumps(error_data)}\n\n".encode("utf-8")
    finally:
        await _session_manager.unsubscribe(actual_session_uid, q)
        log.info(f"Unsubscribed from quiz session {actual_session_uid}")
        
        # Cleanup: If session has no attempts, delete it (user didn't answer any questions)
        try:
            session_query = select(QuizSession).where(QuizSession.session_uid == actual_session_uid)
            session_result = await db.execute(session_query)
            session = session_result.scalar_one_or_none()
            
            if session:
                # Check if there are any attempts for this session
                attempts_count = await db.execute(
                    select(func.count(Attempt.id)).where(Attempt.session_id == session.id)
                )
                total_attempts = attempts_count.scalar() or 0
                
                # If no attempts, delete the session and any associated quiz summary (it was never actually started)
                if total_attempts == 0 and session.status == "initialized":
                    # Delete any associated quiz summary first (if it exists)
                    await db.execute(
                        delete(QuizSummary).where(QuizSummary.session_id == session.id)
                    )
                    # Then delete the session
                    await db.execute(
                        delete(QuizSession).where(QuizSession.id == session.id)
                    )
                    await db.commit()
                    log.info(f"Deleted unstarted session {actual_session_uid} (no answers submitted)")
                elif total_attempts > 0 and session.status == "active":
                    # If session has attempts but is still "active", mark as "completed" since user disconnected
                    # This handles cases where user navigated away or refreshed without explicitly ending
                    # Don't mark as completed if it's already paused (user intentionally paused it)
                    await db.execute(
                        update(QuizSession)
                        .where(QuizSession.id == session.id)
                        .values(status="completed", ended_at=func.now())
                    )
                    await db.commit()
                    log.info(f"Marked disconnected session {actual_session_uid} as completed (had {total_attempts} attempts)")
                elif session.status == "paused":
                    # Don't modify paused sessions - they should remain paused
                    await db.commit()
                    log.info(f"Session {actual_session_uid} is paused, leaving as-is")
                else:
                    await db.commit()
        except Exception as cleanup_error:
            log.error(f"Error cleaning up session {actual_session_uid}: {str(cleanup_error)}")
            await db.rollback()


@router.get("/quiz/start")
async def start_quiz_sse(
    request: Request,
    topic_id: str = Query(..., description="Topic UUID"),
    principal: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Start an SSE-based adaptive quiz session.
    
    IMPORTANT: This endpoint creates a NEW session and returns the session_uid
    in the first SSE event. Your frontend should:
    1. Connect to this endpoint with the topic_id
    2. Listen for the 'session_started' event
    3. Extract and store the session_uid from that event
    4. Use that session_uid for all subsequent answer submissions
    
    This establishes a persistent connection and automatically delivers:
    - Session initialization (with session_uid)
    - First question
    - Adaptive question flow
    - Real-time feedback
    - Session completion
    """
    user_id = principal["id"]
    
    # Debug logging to see what we're actually receiving
    log.info(f"SSE start request - topic_id param: {repr(topic_id)} (type: {type(topic_id).__name__})")

    # Validate topic exists. Accept either the DB UUID (topics.id) or the slug.
    # If the provided topic_id parses as a UUID, use the PK lookup,
    # otherwise treat it as slug and query that column.
    try:
        possible_uuid = UUID(topic_id)
        log.info(f"Parsed as UUID: {possible_uuid}")
        topic_query = select(Topic).where(Topic.id == possible_uuid)
    except (ValueError, TypeError) as e:
        log.info(f"Not a valid UUID ({e}), treating as slug: {topic_id}")
        topic_query = select(Topic).where(Topic.slug == topic_id)

    topic_result = await db.execute(topic_query)
    topic = topic_result.scalar_one_or_none()

    if not topic:
        log.error(f"Topic not found for topic_id: {repr(topic_id)}")
        raise HTTPException(status_code=404, detail=f"Topic not found: {topic_id}")
    
    if not topic.is_published:
        raise HTTPException(status_code=400, detail="Topic is not published")
    
    log.info(f"Starting SSE quiz session for user {user_id} on topic {topic_id}")
    
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Cache-Control"
    }
    
    return StreamingResponse(
        _quiz_sse_stream(request, user_id, topic_id, db),
        headers=headers,
        media_type="text/event-stream"
    )


@router.post("/quiz/{session_uid}/answer")
async def submit_answer_sse(
    answer_data: AnswerSSERequest,
    session_uid: str = Path(..., description="Session identifier"),
    principal: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Submit answer and trigger SSE events for next question or completion."""
    log.info(f"Answer request: {answer_data}")
    log.info(f"Session UID: {session_uid}")
    log.info(f"[CONTROLLER] submit_answer_sse called - session_uid={session_uid}, question_id={answer_data.question_id}")
    
    try:
        # Convert user_id to UUID for consistency, handle invalid UUID gracefully
        try:
            user_id = UUID(principal["id"])
            log.info(f"[CONTROLLER] user_id converted to UUID: {user_id}")
        except (ValueError, TypeError) as e:
            log.error(f"Invalid user_id format in principal: {principal.get('id')}")
            raise HTTPException(status_code=400, detail="Invalid user ID format")
        
        user_role = principal.get("role", "user")
        log.info(f"[CONTROLLER] user_role: {user_role}, calling _session_manager.submit_answer")
        
        # Process the answer
        log.info(f"[CONTROLLER] About to call submit_answer for session {session_uid}")
        result = await _session_manager.submit_answer(
            session_uid=session_uid,
            question_id=answer_data.question_id,
            selected_answer=answer_data.selected_answer,
            elapsed_ms=answer_data.elapsed_ms,
            user_id=user_id,
            user_role=user_role,
            db=db
        )
        
        # Publish answer feedback via SSE (wrap in try-except to prevent errors from blocking response)
        try:
            await _session_manager.publish(session_uid, "answer_feedback", {
                "is_correct": result.get("is_correct", False),
                "correct_answer": result.get("correct_answer", ""),
                "selected_answer": result.get("selected_answer", ""),
                "explanation": result.get("explanation", {}),
                "session_stats": result.get("session_stats", {})
            })
        except Exception as publish_error:
            log.warning(f"Error publishing answer_feedback for session {session_uid}: {str(publish_error)}")
        
        # Send next question or completion
        try:
            if result.get("session_ended", False):
                # Generate and send summary
                try:
                    summary = await _session_manager.get_session_summary(session_uid, user_id, user_role, db)
                    await _session_manager.publish(session_uid, "quiz_completed", summary)
                except Exception as summary_error:
                    log.warning(f"Error generating/publishing summary for session {session_uid}: {str(summary_error)}")
                    # Still publish quiz_completed with basic info
                    await _session_manager.publish(session_uid, "quiz_completed", {
                        "session_uid": session_uid,
                        "message": "Quiz completed"
                    })
            elif result["next_question"]:
                # Send next question
                await _session_manager.publish(session_uid, "question", result["next_question"])
            elif result.get("needs_refill"):
                # Send needs refill event
                await _session_manager.publish(session_uid, "needs_refill", {"session_uid": session_uid})
        except Exception as publish_error:
            log.warning(f"Error publishing next step event for session {session_uid}: {str(publish_error)}")
        
        log.info(f"Answer submitted for session {session_uid}: correct={result.get('is_correct', False)}")
        
        return Envelope(data={
            "success": True,
            "is_correct": result.get("is_correct", False),
            "session_ended": result.get("session_ended", False)
        })
        
    except HTTPException:
        # Re-raise HTTP exceptions (like 400, 404, 403) as-is
        raise
    except Exception as e:
        error_str = str(e)
        error_type = type(e).__name__
        log.error(
            f"Error submitting answer for session {session_uid}: {error_type}: {error_str}",
            exc_info=True  # Include full traceback in logs
        )
        
        # Check if this is a database timeout error
        is_timeout = (
            "timeout" in error_str.lower() or
            "QueryCanceledError" in error_str or
            "statement timeout" in error_str.lower() or
            "QueryCanceledError" in error_type
        )
        
        # Send error via SSE (wrap in try-except to prevent double errors)
        error_message = (
            "The request timed out. Please try submitting your answer again."
            if is_timeout
            else "An error occurred while submitting your answer. Please try again."
        )
        
        try:
            await _session_manager.publish(session_uid, "error", {
                "message": error_message,
                "type": "answer_submission_error",
                "is_timeout": is_timeout
            })
        except Exception as publish_error:
            log.warning(f"Failed to publish error event for session {session_uid}: {str(publish_error)}")
        
        # Return user-friendly error message instead of raw database error
        if is_timeout:
            raise HTTPException(
                status_code=504,  # Gateway Timeout
                detail="The request timed out. Please try submitting your answer again."
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="An error occurred while submitting your answer. Please try again."
            )


@router.get("/quiz/{session_uid}/summary")
async def get_quiz_summary(
    session_uid: str = Path(..., description="Session identifier"),
    principal: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Get comprehensive quiz summary with analytics and recommendations."""
    user_id = UUID(principal["id"])
    
    try:
        user_role = principal.get("role", "user")
        summary = await _session_manager.get_session_summary(session_uid, user_id, user_role, db)
        
        log.info(f"Quiz summary requested for session {session_uid}")
        
        return Envelope(data=summary)
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error getting summary for session {session_uid}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quiz/{session_uid}/pause")
async def pause_quiz_session(
    session_uid: str = Path(..., description="Session identifier"),
    principal: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Pause a quiz session so it can be resumed later.
    
    This endpoint:
    1. Marks the session as "paused" in the database
    2. Does NOT set ended_at (session is still in progress)
    3. Publishes a connection_close event to signal the client to disconnect
    4. Returns success immediately
    
    The session can be resumed later by connecting to the same topic.
    """
    user_id = UUID(principal["id"])
    user_role = principal.get("role", "user")
    
    try:
        # Verify session exists and belongs to user
        session_query = select(QuizSession).where(QuizSession.session_uid == session_uid)
        session_result = await db.execute(session_query)
        session = session_result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Authorization: user can only pause their own session (unless admin)
        if session.user_id != user_id and user_role not in ["admin", "super_admin", "org_admin"]:
            raise HTTPException(status_code=403, detail="Not authorized to pause this session")
        
        # Check if there are any attempts for this session
        attempts_count = await db.execute(
            select(func.count(Attempt.id)).where(Attempt.session_id == session.id)
        )
        total_attempts = attempts_count.scalar() or 0
        
        # Can only pause sessions that have at least one attempt (active sessions)
        if total_attempts == 0:
            raise HTTPException(status_code=400, detail="Cannot pause a session with no attempts")
        
        if session.status == "completed":
            raise HTTPException(status_code=400, detail="Cannot pause a completed session")
        
        # Mark session as paused (do NOT set ended_at)
        await db.execute(
            update(QuizSession)
            .where(QuizSession.id == session.id)
            .values(status="paused")
        )
        await db.commit()
        
        # Publish connection_close event to signal client to disconnect
        await _session_manager.publish(session_uid, "connection_close", {
            "message": "Session paused",
            "session_uid": session_uid,
            "timestamp": int(time.time())
        })
        
        log.info(f"Session {session_uid} paused by user {user_id}")
        
        return Envelope(data={
            "success": True,
            "message": "Session paused successfully",
            "session_uid": session_uid,
            "status": "paused"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error pausing session {session_uid}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quiz/{session_uid}/end")
async def end_quiz_session(
    session_uid: str = Path(..., description="Session identifier"),
    principal: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Force-end a quiz session and close the SSE stream.
    
    This endpoint:
    1. Marks the session as completed in the database
    2. Publishes a quiz_completed event via SSE (if session has subscribers)
    3. Publishes a connection_close event to signal the client to disconnect
    4. Returns success immediately
    
    The client should listen for the 'connection_close' event and call es.close()
    to properly terminate the SSE connection.
    """
    try:
        # Convert user_id to UUID, handle invalid UUID gracefully
        try:
            user_id = UUID(principal["id"])
        except (ValueError, TypeError) as e:
            log.error(f"Invalid user_id format in principal: {principal.get('id')}")
            raise HTTPException(status_code=400, detail="Invalid user ID format")
        
        user_role = principal.get("role", "user")
        # Verify session exists and belongs to user
        session_query = select(QuizSession).where(QuizSession.session_uid == session_uid)
        session_result = await db.execute(session_query)
        session = session_result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Authorization: user can only end their own session (unless admin)
        if session.user_id != user_id and user_role not in ["admin", "super_admin", "org_admin"]:
            raise HTTPException(status_code=403, detail="Not authorized to end this session")
        
        # Check if there are any attempts for this session
        attempts_count = await db.execute(
            select(func.count(Attempt.id)).where(Attempt.session_id == session.id)
        )
        total_attempts = attempts_count.scalar() or 0
        
        # If no attempts, delete the session and any associated quiz summary instead of marking as completed
        if total_attempts == 0 and session.status == "initialized":
            # Delete any associated quiz summary first (if it exists)
            await db.execute(
                delete(QuizSummary).where(QuizSummary.session_id == session.id)
            )
            # Then delete the session
            await db.execute(
                delete(QuizSession).where(QuizSession.id == session.id)
            )
            await db.commit()
            log.info(f"Deleted unstarted session {session_uid} (ended without answering)")
            return Envelope(data={
                "success": True,
                "message": "Session deleted (no answers submitted)",
                "session_uid": session_uid,
                "status": "deleted"
            })
        
        # Mark session as completed
        await db.execute(
            update(QuizSession)
            .where(QuizSession.id == session.id)
            .values(status='completed', ended_at=func.now())
        )
        await db.commit()
        
        # Get final summary (wrap in try-except to handle potential errors gracefully)
        summary = None
        try:
            summary = await _session_manager.get_session_summary(session_uid, user_id, user_role, db)
        except Exception as summary_error:
            log.warning(f"Error generating summary for session {session_uid}: {str(summary_error)}")
            # Continue without summary - session is still marked as completed
        
        # Publish quiz_completed event to SSE subscribers (if summary available)
        if summary:
            try:
                await _session_manager.publish(session_uid, "quiz_completed", summary)
            except Exception as publish_error:
                log.warning(f"Error publishing quiz_completed event for session {session_uid}: {str(publish_error)}")
        
        # Publish connection_close event to signal client to disconnect
        try:
            await _session_manager.publish(session_uid, "connection_close", {
                "message": "Session ended by user request",
                "session_uid": session_uid,
                "timestamp": int(time.time())
            })
        except Exception as publish_error:
            log.warning(f"Error publishing connection_close event for session {session_uid}: {str(publish_error)}")
        
        log.info(f"Session {session_uid} force-ended by user {user_id}")
        
        return Envelope(data={
            "success": True,
            "message": "Session ended successfully",
            "session_uid": session_uid,
            "status": "completed",
            "summary": summary if summary else None
        })
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error ending session {session_uid}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Legacy endpoint for backward compatibility
@router.get("/quizzes/{sid}/stream")
async def legacy_stream(
    request: Request, 
    sid: str = Path(..., description="Session UID / quiz_id")
) -> StreamingResponse:
    """Legacy SSE endpoint - redirects to new implementation."""
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream; charset=utf-8",
    }
    
    async def legacy_stream_generator():
        yield b"event: info\ndata: {\"message\": \"This endpoint is deprecated. Please use /sse/quiz/start?topic_id=<uuid> instead\"}\n\n"
    
    return StreamingResponse(legacy_stream_generator(), headers=headers, media_type="text/event-stream")