"""DB-free unit tests for worker utilities (Module 3)."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.features.llm.schema import QuestionItem
from app.features.llm.worker import (
    _call_llm_generate,
    _compute_question_hash,
    _items_to_import,
    _maybe_upload_s3,
)


def test_llm_call_default_raises() -> None:
    with pytest.raises(NotImplementedError):
        # Note: function is async; call via pytest/asyncio or run loop.
        import asyncio

        asyncio.run(_call_llm_generate(topic_slug="algebra", n=1))


def test_compute_question_hash_deterministic_and_topic_bound() -> None:
    topic_a = UUID("00000000-0000-0000-0000-0000000000aa")
    topic_b = UUID("00000000-0000-0000-0000-0000000000bb")

    item = QuestionItem(
        body=" What is 1 + 1? ",
        choices={"A": "2", "B": "3"},
        correct_answer="A",
        difficulty=1,
    )

    h1 = _compute_question_hash(topic_a, item)
    h2 = _compute_question_hash(topic_a, item)
    h3 = _compute_question_hash(topic_b, item)

    assert h1 == h2, "hash must be deterministic"
    assert h1 != h3, "hash must differ across topics"


def test_items_to_import_maps_fields() -> None:
    topic = UUID("00000000-0000-0000-0000-0000000000aa")
    items = [
        QuestionItem(body="1+1?", choices={"A": "2", "B": "3"}, correct_answer="A", difficulty=1),
        QuestionItem(body="2+2?", choices={"A": "4", "B": "5"}, correct_answer="A", difficulty=1),
    ]
    out = _items_to_import(topic, items)
    assert len(out) == 2
    assert out[0].body == "1+1?"
    assert out[0].choices["A"] == "2"
    assert out[0].correct_answer == "A"
    # Must contain a computed question_hash
    assert isinstance(out[0].question_hash, str) and len(out[0].question_hash) == 64


def test_maybe_upload_s3_no_bucket_returns_none() -> None:
    # No bucket configured → no upload attempt
    assert _maybe_upload_s3(bucket=None, key="k", data=b"{}") is None
