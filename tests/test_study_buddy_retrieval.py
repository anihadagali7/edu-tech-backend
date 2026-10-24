"""Unit tests for Study Buddy retrieval helpers."""

from __future__ import annotations

import pytest

from app.features.study_buddy.retrieval import (
    ResolvedContext,
    build_retrieval_query,
    retrieve_documents,
    set_vector_client_for_testing,
)
from app.features.study_buddy.schemas import ContextSnapshot, StudyMode


class _FakeVectorClient:
    backend = "fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def search(self, *, namespace: str, query_text: str, filters: dict[str, object], top_k: int) -> list[dict[str, object]]:
        self.calls.append(
            {
                "namespace": namespace,
                "query_text": query_text,
                "filters": filters,
                "top_k": top_k,
            }
        )
        return [
            {
                "id": "doc-1",
                "title": "Doc One",
                "score": 0.9,
                "content": "A helpful explanation",
                "metadata": {"filters": filters},
            },
            {
                "id": "doc-2",
                "title": "Doc Two",
                "score": 0.7,
                "content": "Another helpful explanation",
                "metadata": {"filters": filters},
            },
        ]


def _base_context(**kwargs: object) -> ResolvedContext:
    snapshot = kwargs.get("snapshot") or ContextSnapshot(topic_id="topic-1", learning_material_id="mat-1", question_id="q-1")
    learner_state = kwargs.get("learner_state") or {"difficulty": "medium", "skills": ["fractions"], "recent_messages": []}
    return ResolvedContext(snapshot=snapshot, materials=[], quiz_items=[], learner_state=learner_state)


def test_build_retrieval_query_includes_filters_and_last_error() -> None:
    context = _base_context(
        learner_state={
            "difficulty": "medium",
            "skills": ["fractions"],
            "recent_messages": [
                {"role": "user", "content": "I'm still confused about factoring."},
            ],
        }
    )

    query = build_retrieval_query(mode=StudyMode.QUIZ, context=context, last_error="missed factoring step")

    assert query["namespace"] == "study-buddy:quiz"
    assert query["top_k"] == 3
    assert query["filters"]["topic_id"] == "topic-1"
    assert query["filters"]["difficulty"] == "medium"
    assert "missed factoring step" in query["query_text"]
    assert "I'm still confused" in query["query_text"]


@pytest.mark.asyncio
async def test_retrieve_documents_uses_vector_client_filters() -> None:
    fake_client = _FakeVectorClient()
    set_vector_client_for_testing(fake_client)

    context = _base_context(
        snapshot=ContextSnapshot(topic_id="topic-2", learning_material_id="mat-9"),
        learner_state={
            "difficulty": "hard",
            "skills": ["calculus"],
            "recent_messages": [
                {"role": "assistant", "content": "Remember derivative rules."},
                {"role": "user", "content": "How do I find the slope again?"},
            ],
        },
    )

    results = await retrieve_documents(mode=StudyMode.READING, context=context)

    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["filters"]["topic_id"] == "topic-2"
    assert call["top_k"] == 5
    assert "How do I find the slope" in call["query_text"]

    assert results
    assert context.retrieval_metadata["backend"] == "fake"
    assert context.retrieval_metadata["query"]["filters"]["material_id"] == "mat-9"

    set_vector_client_for_testing(None)
