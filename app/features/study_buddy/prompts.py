"""Prompt templates and builders for Study Buddy tutor interactions."""

from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources
from typing import Any, Mapping

from app.features.study_buddy.schemas import StudyMode

_TEMPLATE_MAP = {
    StudyMode.QUIZ: "tutor_quiz_mode_template.md",
    StudyMode.READING: "tutor_study_mode_template.md",
    StudyMode.REVIEW: "tutor_study_mode_template.md",
    StudyMode.PLANNING: "tutor_study_mode_template.md",
}

_RE_PLACEHOLDER = re.compile(r"{{\s*([\w_]+)\s*}}")


@lru_cache(maxsize=8)
def _load_template(filename: str) -> str:
    return resources.files("prompts").joinpath(filename).read_text(encoding="utf-8")


def _render_template(template: str, values: Mapping[str, Any]) -> str:
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = values.get(key, "")
        return "" if value is None else str(value)

    return _RE_PLACEHOLDER.sub(_replace, template)


def build_system_prompt(mode: StudyMode) -> str:
    """Return a deterministic system prompt describing tutor persona and guardrails."""

    template_name = _TEMPLATE_MAP.get(mode)
    if not template_name:
        raise ValueError(f"Unsupported study mode: {mode}")

    template = _load_template(template_name)
    persona: str
    if mode == StudyMode.QUIZ:
        persona = (
            "You are an encouraging quiz coach who guides students to the answer "
            "without revealing it outright. Offer Socratic hints, highlight reasoning steps, "
            "and refuse to provide final answers."
        )
    elif mode == StudyMode.PLANNING:
        persona = (
            "You are a planning mentor helping learners break down goals into achievable study steps while "
            "referencing recent performance. Emphasize prioritization and reflection."
        )
    else:
        persona = (
            "You are an empathetic study tutor who explains concepts in multiple ways, references "
            "related materials, and encourages metacognition."
        )

    guardrails = (
        "Follow institutional safety policies, avoid sensitive content, and only cite materials provided in "
        "the retrieved snippets. Keep responses under 220 words unless explicitly instructed otherwise."
    )

    return f"{persona}\n\nGuidance Template:\n{template}\n\n{guardrails}"


def build_user_prompt_template(mode: StudyMode, context: Mapping[str, Any]) -> str:
    """Construct the user prompt body with context-aware placeholders populated."""

    template_name = _TEMPLATE_MAP.get(mode)
    if not template_name:
        raise ValueError(f"Unsupported study mode: {mode}")

    template = _load_template(template_name)

    default_values: dict[str, Any] = {
        "mastery_state": context.get("mastery_state", "unknown"),
        "hint_level": context.get("hint_level", 0),
        "question_stem": context.get("question_stem", ""),
        "learner_attempt": context.get("learner_message", ""),
        "policy_url": context.get("policy_url", "https://docs.example.com/study-buddy/policies"),
        "topic_name": context.get("topic_name", "current topic"),
        "focus_concept": context.get("focus_concept", context.get("question_stem", "focus concept")),
        "misunderstandings": context.get("misunderstandings", context.get("last_error", "")),
        "learning_objective": context.get("learning_objective", context.get("goal", "reinforce mastery")),
    }

    rendered = _render_template(template, default_values)

    sections: list[str] = [rendered.strip()]

    learner_message = str(context.get("learner_message", "")).strip()
    if learner_message:
        sections.append("## Learner Message\n" + learner_message)

    retrieved = context.get("retrieved_snippets", "")
    sections.append("## Retrieved Snippets\n" + (retrieved or "(no relevant snippets retrieved)"))

    context_notes = context.get("context_notes")
    if context_notes:
        sections.append("## Session Context\n" + str(context_notes))

    return "\n\n".join(section for section in sections if section)
