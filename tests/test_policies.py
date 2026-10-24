# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""Unit tests for Study Buddy hint policies and redaction enforcement."""

from app.features.study_buddy.policies import HintPolicy, enforce_quiz_no_answer, select_next_hint_level
from app.features.study_buddy.schemas import StudyMode


def test_select_next_hint_level_quiz_mode() -> None:
    policy = HintPolicy(max_hint_level=2, leak_rules=("no-final-answer",), allowed_tools=())

    # High mastery should keep hints minimal even after several attempts.
    assert select_next_hint_level(policy, mastery_signal=0.9, attempts=3, mode=StudyMode.QUIZ) == 1

    # Low mastery escalates faster but never exceeds the configured ceiling.
    level = select_next_hint_level(policy, mastery_signal=0.1, attempts=3, mode=StudyMode.QUIZ)
    assert level == policy.max_hint_level

    # Study mode is more generous with guidance.
    study_policy = HintPolicy(max_hint_level=3, leak_rules=(), allowed_tools=("concept_graph",))
    assert select_next_hint_level(study_policy, mastery_signal=0.2, attempts=1, mode=StudyMode.READING) == 2


def test_enforce_quiz_no_answer_redaction() -> None:
    text = "Final answer: B. Here is why..."
    sanitized = enforce_quiz_no_answer(text)

    assert "Final answer" not in sanitized
    assert "B" not in sanitized or "[choice hidden]" in sanitized

    # Non-leaking content should remain untouched.
    assert enforce_quiz_no_answer("Think about factoring the expression") == "Think about factoring the expression"
