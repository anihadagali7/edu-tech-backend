"""Module 5: Worker delegation to provider (no network)."""

from __future__ import annotations

import os
import pytest

import app.features.llm.worker as W


@pytest.mark.asyncio
async def test_worker_calls_openai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange env for provider delegation
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    # Monkeypatch provider.generate_questions to avoid network
    payload = {
        "topic_slug": "discrete-math",
        "items": [
            {"body": "What is set union symbol?", "choices": {"A": "∪", "B": "∩"}, "correct_answer": "A", "difficulty": 1}
        ],
    }

    async def fake_generate_questions(topic_slug: str, n: int, **kwargs):  # type: ignore[no-untyped-def]
        assert topic_slug == "discrete-math"
        assert n == 20 or n == 1
        return payload

    import app.features.llm.provider_openai as P
    monkeypatch.setattr(P, "generate_questions", fake_generate_questions)

    # Act
    out = await W._call_llm_generate(topic_slug="discrete-math", n=20)
    # Assert
    assert out == payload


@pytest.mark.asyncio
async def test_worker_raises_without_provider() -> None:
    # Ensure NotImplementedError when no provider configured
    if "LLM_PROVIDER" in os.environ:
        del os.environ["LLM_PROVIDER"]
    with pytest.raises(NotImplementedError):
        await W._call_llm_generate(topic_slug="x", n=1)
