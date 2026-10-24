"""OpenAI provider adapter for question generation using LangChain.

This adapter uses LangChain's ChatOpenAI async client to call the model in
JSON-mode (when supported). It builds messages from the local prompt
templates, invokes the LLM, parses the returned JSON, validates it with
`TopicQuestionsArtifact` and returns a plain dict.

Environment variables:
- OPENAI_MODEL (default: "gpt-4o-mini")
- OPENAI_API_KEY (required at runtime)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

from app.features.llm.prompt import create_topic_questions_prompt
from app.features.llm.schema import TopicQuestionsArtifact

log = logging.getLogger("llm.openai")


try:
    # Prefer the modern langchain import
    from langchain.chat_models import ChatOpenAI
    from langchain.schema import SystemMessage, HumanMessage
except Exception:
    try:
        # Fallback used elsewhere in repo
        from langchain_openai import ChatOpenAI  # type: ignore
        from langchain.schema import SystemMessage, HumanMessage  # type: ignore
    except Exception as e:  # pragma: no cover - tests will inject a fake client
        raise RuntimeError("LangChain ChatOpenAI is required for provider_openai. Install langchain and langchain-openai.") from e


def _build_messages(slug: str, n: int, topic_name: str = None, topic_description: str = None):
    # The prompt module exposes a helper that returns LangChain message objects.
    display_name = topic_name or slug.replace("-", " ").title()
    return create_topic_questions_prompt(
        topic_slug=slug, 
        topic_display_name=display_name, 
        topic_hint_description=topic_description,
        batch_size=n
    )


def _parse_and_validate_json(content: str, expected_topic_slug: str = None) -> dict:
    data = json.loads(content)

    # Normalize topic slug to match expected format
    if expected_topic_slug and "topic" in data:
        if isinstance(data["topic"], dict) and "slug" in data["topic"]:
            # Force the topic slug to match what was requested
            data["topic"]["slug"] = expected_topic_slug
    
    # Lightweight normalization to tolerate minor LLM formatting deviations.
    for it in data.get("items", []) or []:
        # Normalize correct_answer
        ca = it.get("correct_answer")
        if isinstance(ca, str):
            parts = [p.strip().upper() for p in ca.replace(",", "|").split("|") if p.strip()]
            if parts:
                it["correct_answer"] = parts[0]
        
        # Ensure all distractor explanations exist
        explanations = it.get("explanations", {})
        distractors = explanations.get("distractors", {})
        for choice in ["A", "B", "C", "D"]:
            if choice not in distractors:
                distractors[choice] = ""
        explanations["distractors"] = distractors
        it["explanations"] = explanations

    art = TopicQuestionsArtifact.model_validate(data)
    return art.model_dump(mode="json")


async def generate_questions(
    topic_slug: str, 
    n: int, 
    *, 
    client: Optional[ChatOpenAI] = None,
    topic_name: str = None,
    topic_description: str = None
) -> Dict[str, Any]:
    """Generate and validate questions using LangChain ChatOpenAI.

    Args:
        topic_slug: kebab-case topic slug
        n: number of questions to request
        client: optional ChatOpenAI instance (useful for tests)
        topic_name: actual topic name from database
        topic_description: topic description from database

    Returns:
        dict validated by TopicQuestionsArtifact
    """
    # Use GPT-4 for high-quality question generation
    model = os.getenv("OPENAI_MODEL", "gpt-4")

    # Determine whether the model supports JSON-mode and pass model_kwargs
    json_mode_models = {"gpt-4o-mini", "gpt-4o", "gpt-4-1106-preview", "gpt-3.5-turbo-1106", "gpt-4-turbo-preview"}
    model_kwargs = {}
    if any(m in model for m in json_mode_models):
        model_kwargs["response_format"] = {"type": "json_object"}

    if client is None:
        # Lazily create a LangChain ChatOpenAI client with lower temperature for consistent questions
        client = ChatOpenAI(model=model, temperature=0.2, model_kwargs=model_kwargs)

    messages = _build_messages(topic_slug, n, topic_name, topic_description)

    t0 = time.monotonic()
    # LangChain's async invocation; worker/runner previously used `ainvoke`
    resp = await client.ainvoke(messages)  # type: ignore[attr-defined]
    dt_ms = int((time.monotonic() - t0) * 1000)

    # Extract content and validate
    content = (getattr(resp, "content", None) or "").strip()
    # Some providers may wrap JSON in markdown fences; strip them
    if content.startswith("```json"):
        content = content[7:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    result = _parse_and_validate_json(content, expected_topic_slug=topic_slug)

    log.info("openai_generate_ok", extra={"model": model, "topic_slug": topic_slug, "n": n, "duration_ms": dt_ms})
    return result