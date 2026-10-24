# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""Unit tests for the leak classifier heuristics and explanations."""

from app.features.study_buddy.leak_classifier import LeakClassifier


def test_is_leak_detects_answer_patterns() -> None:
    classifier = LeakClassifier()

    leaking_text = "The correct answer is 42. Final answer: 42"
    assert classifier.is_leak(leaking_text) is True

    safe_text = "Consider reviewing the definition before attempting the next step."
    assert classifier.is_leak(safe_text) is False


def test_explain_returns_structured_metadata() -> None:
    classifier = LeakClassifier()
    metadata = classifier.explain("Answer: B")

    assert metadata["is_leak"] is True
    assert set(metadata.keys()) == {"is_leak", "confidence", "reasons", "matches"}
    assert metadata["reasons"]
    assert "answer_letter" in metadata["matches"]
    assert 0 <= metadata["confidence"] <= 1
