# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""Study Buddy tutor orchestration service for coordinating retrieval, LLM streaming, and persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import textwrap
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional
from uuid import uuid4

try:  # Optional dependency for real LLM streaming; falls back to mock when absent.
    from langchain_openai import ChatOpenAI
    from langchain.schema import HumanMessage, SystemMessage
except Exception:  # pragma: no cover - optional dependency guard
    ChatOpenAI = None  # type: ignore[assignment]
    HumanMessage = SystemMessage = None

from app.features.study_buddy import ENABLE_STUDY_BUDDY
from app.features.study_buddy.prompts import build_system_prompt, build_user_prompt_template
from app.features.study_buddy.schemas import (
    ContextSnapshot,
    HintMeta,
    StudyMessageRequest,
    StudyMessageResponse,
    StudyMode,
    TutorDone,
    TutorTokenChunk,
)
from app.features.study_buddy.repositories import StudyBuddyRepository  # TODO: confirm repository class naming
from app.features.study_buddy.retrieval import ResolvedContext, resolve_context, retrieve_documents  # TODO: confirm class availability
from app.features.study_buddy.policies import (
    HintPolicy,
    PolicyViolation,
    enforce_quiz_no_answer,
    select_next_hint_level,
)
from app.utils.errors import AppError, STB404_SESSION_NOT_FOUND

log = logging.getLogger("study_buddy.service")

_ = (TutorTokenChunk, TutorDone, StudyBuddyRepository, ResolvedContext)


DEFAULT_POLICIES: Dict[StudyMode, HintPolicy] = {
    StudyMode.QUIZ: HintPolicy(max_hint_level=2, leak_rules=("no-final-answer",), allowed_tools=()),
    StudyMode.READING: HintPolicy(max_hint_level=3, leak_rules=(), allowed_tools=("concept_graph",)),
    StudyMode.REVIEW: HintPolicy(max_hint_level=3, leak_rules=(), allowed_tools=("concept_graph",)),
    StudyMode.PLANNING: HintPolicy(max_hint_level=1, leak_rules=(), allowed_tools=()),
}


@dataclass(slots=True)
class StreamEvent:
    """Structured SSE event with helper constructors and serialization utilities."""

    event: str
    payload: dict[str, Any]
    sequence: int

    def to_sse_payload(self) -> str:
        data = json.dumps(self.payload, separators=(",", ":"), default=str)
        return f"id: {self.sequence}\nevent: {self.event}\ndata: {data}\n\n"

    @classmethod
    def from_hint(cls, sequence: int, *, level: int, remaining: int, exhausted: bool, sources: list[str] | None = None) -> "StreamEvent":
        return cls(
            event="hint_meta",
            sequence=sequence,
            payload={
                "level": level,
                "remaining": remaining,
                "exhausted": exhausted,
                "sources": sources or [],
            },
        )

    @classmethod
    def from_token(cls, sequence: int, *, index: int, text: str, latency_ms: float | None = None) -> "StreamEvent":
        payload = {"index": index, "text": text}
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms
        return cls(event="token", sequence=sequence, payload=payload)

    @classmethod
    def from_done(
        cls,
        sequence: int,
        *,
        message_id: str,
        tokens: int,
        follow_up_job_id: str | None,
        sources: list[str],
        backend: str | None,
    ) -> "StreamEvent":
        payload = {
            "message_id": message_id,
            "tokens": tokens,
            "follow_up_job_id": follow_up_job_id,
            "sources": sources,
        }
        if backend:
            payload["backend"] = backend
        return cls(event="done", sequence=sequence, payload=payload)


@dataclass
class _SessionState:
    session_id: str
    user_id: str
    mode: StudyMode
    context: Optional[ContextSnapshot]
    hint: HintMeta = field(default_factory=HintMeta)
    latest_tutor_message: Optional[str] = None
    pending_message: Optional[StudyMessageRequest] = None
    analytics: list[dict[str, Any]] = field(default_factory=list)
    sequence_counter: int = 0


_SESSIONS: Dict[str, _SessionState] = {}
_LOCK = asyncio.Lock()
_LLM_RESPONDER: Callable[[StudyMode, Dict[str, Any]], Awaitable[str]] | None = None
_LLM_CLIENT: Any | None = None


def set_llm_responder_for_testing(  # pragma: no cover - used only in tests
    responder: Callable[[StudyMode, Dict[str, Any]], Awaitable[str]] | None,
) -> None:
    """Allow tests to inject a deterministic responder without patching internals."""

    global _LLM_RESPONDER
    _LLM_RESPONDER = responder


def _ensure_feature_enabled() -> None:
    if not ENABLE_STUDY_BUDDY:
        raise RuntimeError("Study Buddy feature is disabled")


def _sse_url(session_id: str) -> str:
    return f"/sse/study-buddy/{session_id}"


def _session_response(state: _SessionState) -> StudyMessageResponse:
    return StudyMessageResponse(
        session_id=state.session_id,
        mode=state.mode,
        hint=state.hint,
        context=state.context,
        latest_tutor_message=state.latest_tutor_message,
        sse_url=_sse_url(state.session_id),
    )


async def start_session(user_id: str, payload: Any, repository: StudyBuddyRepository | None = None) -> StudyMessageResponse:
    from app.features.study_buddy.schemas import StartStudySessionRequest  # local import to avoid cycle

    _ensure_feature_enabled()
    if not isinstance(payload, StartStudySessionRequest):  # defensive guard
        raise TypeError("payload must be StartStudySessionRequest")

    session_id = str(uuid4())
    
    # Persist to DB if repository provided, else fall back to in-memory
    if repository:
        context_snap = payload.context or ContextSnapshot()
        db_session = await repository.create_study_session(
            user_id=user_id,
            payload=context_snap,
            mode=payload.mode.value,
        )
        session_id = str(db_session.id)
        policy = DEFAULT_POLICIES.get(payload.mode, DEFAULT_POLICIES[StudyMode.READING])
        state = _SessionState(
            session_id=session_id,
            user_id=user_id,
            mode=payload.mode,
            context=context_snap,
        )
        state.hint.remaining = policy.max_hint_level
        state.hint.exhausted = policy.max_hint_level == 0
        async with _LOCK:
            _SESSIONS[session_id] = state
    else:
        state = _SessionState(
            session_id=session_id,
            user_id=user_id,
            mode=payload.mode,
            context=payload.context,
        )
        async with _LOCK:
            _SESSIONS[session_id] = state
            policy = DEFAULT_POLICIES.get(state.mode, DEFAULT_POLICIES[StudyMode.READING])
            state.hint.remaining = policy.max_hint_level
            state.hint.exhausted = policy.max_hint_level == 0

    return _session_response(state)


async def get_session(user_id: str, session_id: str, repository: StudyBuddyRepository | None = None) -> _SessionState:
    _ensure_feature_enabled()
    
    # Try DB first if repository provided
    if repository:
        try:
            db_session = await repository.get_session(user_id=user_id, session_id=session_id)
            # Hydrate _SessionState from DB entity
            context_snap = None
            if db_session.context_snapshot:
                try:
                    context_snap = ContextSnapshot.model_validate(db_session.context_snapshot)
                except Exception:  # pragma: no cover - defensive
                    context_snap = ContextSnapshot()
            
            state = _SessionState(
                session_id=str(db_session.id),
                user_id=db_session.user_clerk_id,
                mode=StudyMode(db_session.mode),
                context=context_snap,
            )
            state.hint.level = db_session.hint_level
            state.hint.remaining = max(0, db_session.hint_budget - db_session.hint_level)
            state.hint.exhausted = state.hint.remaining == 0
            
            # Cache in memory for fast access
            async with _LOCK:
                _SESSIONS[session_id] = state
            return state
        except AppError:
            # Session not found in DB, fall through to in-memory check
            pass
    
    # Fall back to in-memory
    async with _LOCK:
        state = _SESSIONS.get(session_id)
    if state is None or state.user_id != user_id:
        raise AppError("session not found", code=STB404_SESSION_NOT_FOUND, status=404)
    return state


async def get_session_response(user_id: str, session_id: str, repository: StudyBuddyRepository | None = None) -> StudyMessageResponse:
    state = await get_session(user_id, session_id, repository)
    return _session_response(state)


async def post_message(user_id: str, session_id: str, message: StudyMessageRequest, repository: StudyBuddyRepository | None = None) -> StudyMessageResponse:
    _ensure_feature_enabled()
    async with _LOCK:
        state = _SESSIONS.get(session_id)
        if state is None or state.user_id != user_id:
            # Try to load from DB if repository available
            if repository:
                try:
                    state = await get_session(user_id, session_id, repository)
                except AppError:
                    raise AppError("session not found", code=STB404_SESSION_NOT_FOUND, status=404)
            else:
                raise AppError("session not found", code=STB404_SESSION_NOT_FOUND, status=404)
        
        state.sequence_counter += 1
        if message.mode is not None:
            state.mode = message.mode
        if message.context is not None:
            state.context = message.context
        
        # Persist user message immediately to DB
        if repository:
            try:
                await repository.append_message(
                    session_id=session_id,
                    user_id=user_id,
                    role="user",
                    content=message.message,
                    hint_level=state.hint.level,
                )
            except Exception as exc:  # pragma: no cover - defensive persistence guard
                log.warning("failed_to_persist_user_message", extra={"session_id": session_id}, exc_info=exc)
        
        state.pending_message = message
        
        # Persist context update to DB if repository provided
        if repository and message.context:
            try:
                await repository.update_session_context(session_id, message.context)
            except Exception:  # pragma: no cover - defensive
                pass
    
    return _session_response(state)


async def record_analytics(user_id: str, session_id: str, payload: dict[str, Any]) -> None:
    _ensure_feature_enabled()
    async with _LOCK:
        state = _SESSIONS.get(session_id)
        if state is None or state.user_id != user_id:
            raise AppError("session not found", code=STB404_SESSION_NOT_FOUND, status=404)
        state.analytics.append(dict(payload))


async def dequeue_pending_message(session_id: str) -> tuple[_SessionState, StudyMessageRequest | None]:
    async with _LOCK:
        state = _SESSIONS.get(session_id)
        if state is None:
            raise AppError("session not found", code=STB404_SESSION_NOT_FOUND, status=404)
        message = state.pending_message
        state.pending_message = None
    return state, message


async def generate_tutor_reply(
    repository: StudyBuddyRepository | None,
    session_id: str,
    message: StudyMessageRequest,
    context: ResolvedContext | None,
) -> AsyncGenerator[StreamEvent, None]:
    """Stream tutor reply events by orchestrating context resolution, retrieval, LLM invocation, and persistence."""

    _ensure_feature_enabled()

    state, pending_message = await dequeue_pending_message(session_id)
    active_message = pending_message or message
    effective_mode = active_message.mode or state.mode
    policy = DEFAULT_POLICIES.get(effective_mode, DEFAULT_POLICIES[StudyMode.READING])

    next_level = select_next_hint_level(
        policy,
        mastery_signal=state.hint.level / max(policy.max_hint_level, 1) if policy.max_hint_level else 0,
        attempts=max(1, state.sequence_counter),
        mode=effective_mode,
    )
    state.hint.level = next_level
    state.hint.remaining = max(0, policy.max_hint_level - next_level)
    state.hint.exhausted = state.hint.remaining == 0

    async with _LOCK:
        live_state = _SESSIONS.get(session_id)
        if live_state is not None:
            live_state.mode = effective_mode
            live_state.hint.level = state.hint.level
            live_state.hint.remaining = state.hint.remaining
            live_state.hint.exhausted = state.hint.exhausted

    explicit_ctx = active_message.context or state.context or ContextSnapshot()
    resolved_context = context or await resolve_context(repository, session_id, explicit_ctx)
    if resolved_context.snapshot is None or resolved_context.snapshot == ContextSnapshot():
        resolved_context.snapshot = explicit_ctx

    try:
        retrieved_docs = await retrieve_documents(
            mode=effective_mode,
            context=resolved_context,
            last_error=resolved_context.learner_state.get("last_error"),
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        log.warning("study_buddy_retrieval_failed", extra={"session_id": session_id}, exc_info=exc)
        retrieved_docs = []
    retrieved_titles = [doc.get("title") for doc in retrieved_docs if doc.get("title")]

    prompt_context = {
        "mastery_state": resolved_context.learner_state.get("mastery", "unknown"),
        "hint_level": state.hint.level,
        "question_stem": resolved_context.learner_state.get("question_stem")
        or (retrieved_docs[0].get("content") if retrieved_docs and retrieved_docs[0].get("content") else ""),
        "learner_message": active_message.message,
        "topic_name": resolved_context.learner_state.get("topic_name")
        or resolved_context.snapshot.topic_id
        or "current topic",
        "focus_concept": resolved_context.snapshot.learning_material_id
        or (retrieved_titles[0] if retrieved_titles else "focus concept"),
        "misunderstandings": resolved_context.learner_state.get("recent_error")
        or resolved_context.learner_state.get("last_error", ""),
        "learning_objective": resolved_context.learner_state.get("goal", "reinforce mastery"),
        "retrieved_snippets": _render_retrieved_highlights(retrieved_docs),
        "context_notes": resolved_context.learner_state.get("recent_messages"),
        "policy_url": os.getenv("STUDY_BUDDY_POLICY_URL", "https://docs.example.com/study-buddy/policies"),
        "goal": resolved_context.learner_state.get("goal"),
        "last_error": resolved_context.learner_state.get("last_error"),
    }

    system_prompt = build_system_prompt(effective_mode)
    user_prompt = build_user_prompt_template(effective_mode, prompt_context)

    llm_context = {
        "retrieved_titles": retrieved_titles,
        "learner_message": active_message.message,
    }

    raw_response = (await _call_llm(effective_mode, system_prompt, user_prompt, llm_context)).strip()
    if not raw_response:
        raw_response = "I'm reviewing what you shared—here's how we can move forward."

    final_message = raw_response
    if effective_mode == StudyMode.QUIZ:
        try:
            final_message = enforce_quiz_no_answer(final_message)
        except PolicyViolation:
            final_message = "Let's focus on the reasoning steps instead of sharing the final answer."

    token_chunks = _tokenize_for_streaming(final_message)
    if not token_chunks:
        token_chunks = [final_message]

    sequence_cursor = state.sequence_counter
    yield StreamEvent.from_hint(
        sequence_cursor,
        level=state.hint.level,
        remaining=state.hint.remaining,
        exhausted=state.hint.exhausted,
        sources=retrieved_titles,
    )
    sequence_cursor += 1

    for index, chunk in enumerate(token_chunks):
        await asyncio.sleep(0)
        yield StreamEvent.from_token(sequence_cursor, index=index, text=chunk, latency_ms=5.0)
        sequence_cursor += 1

    message_id = str(uuid4())
    tokens_emitted = len(token_chunks)
    if repository is not None:
        try:
            stored = await repository.append_message(
                session_id=session_id,
                user_id=state.user_id,
                role="assistant",
                content=final_message,
                hint_level=state.hint.level,
            )
            message_id = str(getattr(stored, "id", message_id))
            analytics_payload = {
                "event_type": "TUTOR_REPLY",
                "mode": effective_mode.value,
                "token_count": tokens_emitted,
                "source_titles": retrieved_titles,
            }
            await repository.log_study_analytics(session_id=session_id, payload=analytics_payload)
        except Exception as exc:  # pragma: no cover - persistence guard
            log.warning("study_buddy_repo_persist_failed", extra={"session_id": session_id}, exc_info=exc)

    async with _LOCK:
        live_state = _SESSIONS.get(session_id)
        if live_state is not None:
            live_state.latest_tutor_message = final_message
            live_state.sequence_counter = sequence_cursor
            live_state.mode = effective_mode

    yield StreamEvent.from_done(
        sequence_cursor,
        message_id=message_id,
        tokens=tokens_emitted,
        follow_up_job_id=None,
        sources=retrieved_titles,
        backend=(resolved_context.retrieval_metadata or {}).get("backend"),
    )


async def summarize_session(
    repository: StudyBuddyRepository | None,
    session_id: str,
) -> TutorDone:
    """Return a lightweight summary placeholder until background worker integration is ready."""

    _ensure_feature_enabled()
    summary_text = textwrap.dedent(
        f"""Summary for session {session_id}:
        - Review the hints shared in this session.
        - Note remaining confusion points and plan a follow-up task.
        - Revisit referenced materials before the next attempt.
        """
    ).strip()

    if repository is not None:
        try:
            await repository.log_study_analytics(
                session_id=session_id,
                payload={
                    "event_type": "SESSION_SUMMARY",
                    "excerpt": summary_text[:240],
                },
            )
        except Exception as exc:  # pragma: no cover - persistence guard
            log.warning("study_buddy_summary_analytics_failed", extra={"session_id": session_id}, exc_info=exc)

    return TutorDone(message_id=str(uuid4()), tokens=len(summary_text.split()), follow_up_job_id=None)


def reset_state_for_testing() -> None:
    """Clear in-memory session state to keep tests isolated."""

    _SESSIONS.clear()


def _render_retrieved_highlights(results: list[dict[str, Any]]) -> str:
    if not results:
        return "(no relevant snippets retrieved)"

    lines: list[str] = []
    for doc in results[:3]:
        title = doc.get("title") or "Context snippet"
        content = (doc.get("content") or "").strip().replace("\n", " ")
        preview = (content[:220] + "…") if len(content) > 220 else content
        lines.append(f"- {title}: {preview}")
    return "\n".join(lines)


def _tokenize_for_streaming(text_value: str) -> list[str]:
    if not text_value:
        return []
    chunks = textwrap.wrap(text_value, width=60, break_long_words=False, replace_whitespace=False)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _should_use_openai() -> bool:
    flag = os.getenv("STUDY_BUDDY_USE_OPENAI", "0").lower() in {"1", "true", "yes"}
    return bool(flag and ChatOpenAI and os.getenv("OPENAI_API_KEY"))


def _get_llm_client() -> Any | None:
    global _LLM_CLIENT
    if _LLM_CLIENT is not None:
        return _LLM_CLIENT
    if not _should_use_openai():
        return None
    # Use GPT-4 for Study Buddy chat to provide high-quality hints and guidance
    model = os.getenv("STUDY_BUDDY_MODEL") or "gpt-4"
    try:
        # Temperature 0.6 for helpful, focused hints (not too creative, not too rigid)
        _LLM_CLIENT = ChatOpenAI(model=model, temperature=0.6)
    except Exception as exc:  # pragma: no cover - dependency guard
        log.warning("study_buddy_llm_client_init_failed", extra={"model": model}, exc_info=exc)
        _LLM_CLIENT = None
    return _LLM_CLIENT


async def _call_llm(
    mode: StudyMode,
    system_prompt: str,
    user_prompt: str,
    extra_context: Dict[str, Any],
) -> str:
    if _LLM_RESPONDER is not None:
        return await _LLM_RESPONDER(mode, {"system_prompt": system_prompt, "user_prompt": user_prompt, **extra_context})

    client = _get_llm_client()
    if client and HumanMessage and SystemMessage:
        try:
            response = await client.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
            content = getattr(response, "content", "")
            if isinstance(content, list):
                content = "".join(getattr(part, "text", str(part)) for part in content)
            return str(content or "")
        except Exception as exc:  # pragma: no cover - provider guard
            log.warning("study_buddy_llm_openai_error", extra={"mode": mode.value}, exc_info=exc)

    return _mock_llm_response(mode, user_prompt, extra_context)


def _mock_llm_response(mode: StudyMode, user_prompt: str, context: Dict[str, Any]) -> str:
    titles = context.get("retrieved_titles") or []
    intro = (
        "Let's reason through the question by unpacking the key clues."
        if mode == StudyMode.QUIZ
        else "Here's a study-friendly explanation tying everything together."
    )
    sources = f"Referencing {', '.join(titles[:3])}." if titles else ""
    learner_line = user_prompt.splitlines()[-1].strip() if user_prompt else ""
    body = textwrap.dedent(
        f"""{intro} {sources}
        Learner focus: {learner_line or 'Not provided yet.'}
        Step-by-step:
        1. Reframe the goal in your own words.
        2. Connect it to the retrieved snippets.
        3. Plan one concrete next action.
        """
    ).strip()
    return body
