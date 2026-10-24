# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""Utility for detecting answer leakage in tutor outputs using heuristics and optional small models."""

from __future__ import annotations

import re
from typing import Any, Dict, List


class LeakClassifier:
    """Detect whether tutor output leaks answers and provide diagnostic explanations for remediation workflows.

    TODO:
    1. Compile regex patterns for direct-answer phrases, numeric sequences, and explicit solution markers.
    2. Integrate lightweight embedding or small-model inference for nuanced leakage detection beyond regex.
    3. Support configurable sensitivity levels per mode or subject area.
    4. Log decisions and classifier confidence for auditability and future tuning.

    Acceptance:
    - Exposes deterministic `is_leak` and `explain` APIs for other components to consume.
    - Maintains thread-safety for concurrent worker execution.
    - Allows dependency injection of external model clients for advanced analysis.
    """

    def __init__(
        self,
        *,
        numeric_threshold: int = 3,
        letter_threshold: int = 1,
    ) -> None:
        """Initialize regex heuristics and configurable thresholds."""

        self.numeric_threshold = max(1, numeric_threshold)
        self.letter_threshold = max(1, letter_threshold)

        self.patterns: Dict[str, re.Pattern[str]] = {
            "direct_answer_phrase": re.compile(
                r"\b(final\s+answer|correct\s+answer|the\s+answer\s+is|answer\s*[:=])\b",
                re.IGNORECASE,
            ),
            "trailing_numeric_list": re.compile(
                r"(?:^|\n)\s*(?:\d+[.)\-]|[ivxlcdm]+[.)])",
                re.IGNORECASE,
            ),
            "answer_letter": re.compile(
                r"\b(?:answer|option|choice)\s*[:=]?\s*([A-D])\b",
                re.IGNORECASE,
            ),
        }

        self.numeric_pattern = re.compile(r"\b\d+(?:\.\d+)?\b")

        # Placeholder for an optional lightweight model. Leave as TODO until wired.
        self._small_model = None  # TODO: integrate small-model scoring when available.

    def is_leak(self, text: str) -> bool:
        """Return True when heuristics indicate direct answer leakage."""

        if not text or not text.strip():
            return False

        details = self._evaluate(text)
        return details["score"] > 0

    def explain(self, text: str) -> Dict[str, Any]:
        """Return structured metadata describing leakage heuristics."""

        details = self._evaluate(text)
        confidence = min(1.0, details["score"])
        return {
            "is_leak": details["score"] > 0,
            "confidence": confidence,
            "reasons": details["reasons"],
            "matches": details["matches"],
        }

    # Internal helpers -----------------------------------------------------

    def _evaluate(self, text: str) -> Dict[str, Any]:
        stripped = text or ""
        matches: Dict[str, List[str]] = {name: [] for name in self.patterns}
        reasons: List[str] = []
        score = 0.0

        for name, pattern in self.patterns.items():
            results = pattern.findall(stripped)
            if results:
                normalized = [r[0] if isinstance(r, tuple) else r for r in results]
                matches[name].extend(normalized)
                reasons.append(name)
                score += 0.5

        numbers = self.numeric_pattern.findall(stripped)
        if len(numbers) >= self.numeric_threshold:
            matches.setdefault("numeric_sequence", []).extend(numbers[: self.numeric_threshold])
            reasons.append("numeric_sequence")
            score += 0.5

        if matches.get("answer_letter"):
            if len(matches["answer_letter"]) >= self.letter_threshold:
                score += 0.3
        else:
            matches.pop("answer_letter", None)

        matches = {key: value for key, value in matches.items() if value}

        return {
            "score": score,
            "reasons": reasons,
            "matches": matches,
        }
