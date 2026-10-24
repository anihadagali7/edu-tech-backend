"""Context resolution and retrieval query construction for Study Buddy tutor prompts."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select

from app.db.models import Question
from app.features.study_buddy.schemas import ContextSnapshot, StudyMode


@dataclass
class ResolvedContext:
    """Fully hydrated context inputs for tutor prompt construction.

    The structure intentionally mirrors Attachment B requirements so downstream
    services (LLM prompt builder, analytics, SSE) can consume a single object
    without re-querying the database. Optional buckets allow future expansion
    (e.g., knowledge graph nodes) without breaking callers.
    """

    snapshot: ContextSnapshot
    materials: list[Any] = field(default_factory=list)
    quiz_items: list[Any] = field(default_factory=list)
    learner_state: dict[str, Any] = field(default_factory=dict)
    retrieved_documents: list[dict[str, Any]] = field(default_factory=list)
    retrieval_metadata: dict[str, Any] = field(default_factory=dict)


class VectorClient(Protocol):
    """Protocol describing the minimal vector adapter surface we rely on."""

    backend: str

    async def search(
        self,
        *,
        namespace: str,
        query_text: str,
        filters: dict[str, Any],
        top_k: int,
    ) -> list[dict[str, Any]]:  # pragma: no cover - interface definition
        ...


class _BaseVectorClient:
    backend: str = "mock"

    async def search(
        self,
        *,
        namespace: str,
        query_text: str,
        filters: dict[str, Any],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Return deterministic mock data while TODO real adapters wire up."""

        snippet = query_text[:120] or "general help"
        results: list[dict[str, Any]] = []
        for idx in range(max(1, top_k)):
            results.append(
                {
                    "id": f"{self.backend}-{idx}",
                    "title": f"{filters.get('topic_id', 'general')} snippet {idx + 1}",
                    "content": f"{snippet} (match {idx + 1})",
                    "score": 1.0 - (idx * 0.05),
                    "metadata": {
                        "namespace": namespace,
                        "filters": filters,
                    },
                }
            )
        return results


class PgVectorClient(_BaseVectorClient):
    backend = "pgvector"


class PineconeClient(_BaseVectorClient):
    backend = "pinecone"


class MockVectorClient(_BaseVectorClient):
    backend = "mock"


_VECTOR_CLIENT: VectorClient | None = None


def set_vector_client_for_testing(client: VectorClient | None) -> None:
    """Allow unit tests to override the vector adapter without touching env vars."""

    global _VECTOR_CLIENT
    _VECTOR_CLIENT = client


def _get_vector_backend_name() -> str:
    return os.getenv("STUDY_BUDDY_VECTOR_BACKEND", "pgvector").strip().lower()


def get_vector_client() -> VectorClient:
    """Instantiate (and memoize) a vector adapter based on environment selection."""

    global _VECTOR_CLIENT
    if _VECTOR_CLIENT is not None:
        return _VECTOR_CLIENT

    backend = _get_vector_backend_name()
    if backend == "pinecone":
        _VECTOR_CLIENT = PineconeClient()
    elif backend == "pgvector":
        _VECTOR_CLIENT = PgVectorClient()
    else:
        # Fallback mock keeps local/dev environments functional without deps.
        _VECTOR_CLIENT = MockVectorClient()
    return _VECTOR_CLIENT


async def resolve_context(
    repository: Any,
    session_id: str,
    explicit_ctx: Optional[ContextSnapshot],
) -> ResolvedContext:
    """Combine explicit snapshot data with persisted session metadata."""

    snapshot = explicit_ctx or ContextSnapshot()
    materials: list[Any] = []
    quiz_items: list[Any] = []
    learner_state: dict[str, Any] = {"session_id": session_id}

    if repository is None:
        learner_state["source"] = "explicit" if explicit_ctx else "stateless"
        return ResolvedContext(snapshot=snapshot, materials=materials, quiz_items=quiz_items, learner_state=learner_state)

    session_entity = None
    loader = getattr(repository, "_load_session", None)
    if callable(loader):  # pragma: no branch - protective
        session_entity = await loader(session_id)

    if session_entity and getattr(session_entity, "context_snapshot", None):
        try:
            snapshot = ContextSnapshot.model_validate(session_entity.context_snapshot)
        except ValidationError:
            learner_state["context_hydration"] = "invalid_snapshot"

    if session_entity and getattr(session_entity, "topic_id", None):
        learner_state["topic_id"] = str(session_entity.topic_id)

    if session_entity and getattr(session_entity, "material_id", None):
        materials.append(
            {
                "material_id": str(session_entity.material_id),
                "title": getattr(getattr(session_entity, "material", None), "title", None),
            }
        )

    if session_entity and getattr(session_entity, "linked_quiz_session_id", None):
        quiz_items.append({"quiz_session_id": str(session_entity.linked_quiz_session_id)})

    # Fetch question content if question_id is present
    question_id = snapshot.question_id if snapshot else None
    if question_id and repository:
        try:
            # Get the session from repository to query Question
            db_session = getattr(repository, "_session", None)
            if db_session:
                try:
                    question_uuid = UUID(question_id) if isinstance(question_id, str) else question_id
                    stmt = select(Question).where(Question.id == question_uuid)
                    result = await db_session.execute(stmt)
                    question = result.scalar_one_or_none()
                    if question:
                        # Format question stem with body and choices for the prompt
                        choices_text = "\n".join([f"{key}: {value}" for key, value in sorted(question.choices.items())])
                        question_stem = f"Question: {question.body}\n\nChoices:\n{choices_text}"
                        learner_state["question_stem"] = question_stem
                        learner_state["question_body"] = question.body
                        learner_state["question_choices"] = question.choices
                except (ValueError, TypeError):
                    # Invalid UUID format, skip question fetch
                    pass
                except Exception as e:
                    # Other errors fetching question - log but don't fail
                    import logging
                    logging.getLogger("study_buddy.retrieval").warning(f"Failed to fetch question {question_id}: {e}")
        except Exception:  # pragma: no cover - defensive
            pass

    fetch_messages = getattr(repository, "recent_messages_for_session", None)
    if callable(fetch_messages):
        try:
            messages = await fetch_messages(session_id=session_id, limit=5)
            learner_state["recent_messages"] = [
                {
                    "role": getattr(msg, "role", "assistant"),
                    "content": getattr(msg, "content", ""),
                    "hint_level": getattr(msg, "hint_level", None),
                }
                for msg in messages
            ]
        except Exception:  # pragma: no cover - defensive logging hook
            learner_state["recent_messages"] = []
            learner_state["recent_messages_error"] = "repository_failure"

    return ResolvedContext(
        snapshot=snapshot,
        materials=materials,
        quiz_items=quiz_items,
        learner_state=learner_state,
    )


def build_retrieval_query(
    mode: StudyMode,
    context: ResolvedContext,
    last_error: Optional[str],
) -> dict[str, Any]:
    """Produce a deterministic payload for the selected vector backend."""

    namespace = "study-buddy:quiz" if mode == StudyMode.QUIZ else "study-buddy:materials"
    filters: dict[str, Any] = {}

    snapshot = context.snapshot or ContextSnapshot()
    if snapshot.topic_id:
        filters["topic_id"] = snapshot.topic_id
    if snapshot.learning_material_id:
        filters["material_id"] = snapshot.learning_material_id
    if snapshot.question_id:
        filters["question_id"] = snapshot.question_id

    learner_topic = context.learner_state.get("topic_id")
    if learner_topic and "topic_id" not in filters:
        filters["topic_id"] = learner_topic

    difficulty = context.learner_state.get("difficulty")
    if difficulty:
        filters["difficulty"] = difficulty

    skills = context.learner_state.get("skills")
    if skills:
        filters["skills"] = skills

    recent_messages = context.learner_state.get("recent_messages") or []
    recent_user_utterance = next((m for m in reversed(recent_messages) if m.get("role") == "user" and m.get("content")), None)

    fragments: list[str] = []
    if snapshot.question_id:
        fragments.append(f"Question focus {snapshot.question_id}")
    if snapshot.learning_material_id:
        fragments.append(f"Material {snapshot.learning_material_id}")
    if recent_user_utterance:
        fragments.append(recent_user_utterance["content"])
    if last_error:
        fragments.append(f"Learner confusion: {last_error}")

    if not fragments:
        fragments.append("general concept reinforcement")

    top_k = 3 if mode == StudyMode.QUIZ else 5

    return {
        "namespace": namespace,
        "query_text": " \n".join(fragments).strip(),
        "filters": filters,
        "top_k": top_k,
        "mode": mode.value,
    }


async def retrieve_documents(
    mode: StudyMode,
    context: ResolvedContext,
    last_error: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Execute the retrieval pipeline and attach results to the context object."""

    query = build_retrieval_query(mode=mode, context=context, last_error=last_error)
    client = get_vector_client()
    raw_results = await client.search(
        namespace=query["namespace"],
        query_text=query["query_text"],
        filters=query["filters"],
        top_k=query["top_k"],
    )
    ranked_results = rerank_results(raw_results, context)
    context.retrieved_documents = ranked_results
    context.retrieval_metadata = {
        "query": query,
        "backend": client.backend,
    }
    return ranked_results


def rerank_results(results: list[dict[str, Any]], context: ResolvedContext) -> list[dict[str, Any]]:
    """Simple reranker stub prioritizing higher score and matching topic filters."""

    if not results:
        return []

    topic_id = context.snapshot.topic_id or context.learner_state.get("topic_id")

    def _score(entry: dict[str, Any]) -> tuple[int, float]:
        entry_topic = (entry.get("metadata") or {}).get("filters", {}).get("topic_id")
        topic_bonus = 1 if topic_id and entry_topic == topic_id else 0
        base = float(entry.get("score", 0.0))
        return (-topic_bonus, -base)

    ranked = sorted(results, key=_score)
    for index, entry in enumerate(ranked, start=1):
        entry.setdefault("rank", index)
    return ranked

