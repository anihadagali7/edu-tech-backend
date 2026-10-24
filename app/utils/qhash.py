"""Question hash utilities.

Provides a single canonical compute_question_hash used across workers to
avoid drift in deduplication behavior.
"""
from __future__ import annotations

import hashlib
from typing import Any


def _normalize_text(s: Any) -> str:
    if s is None:
        return ""
    # collapse whitespace and lowercase for stable normalization
    return " ".join(str(s).strip().split()).lower()


def compute_question_hash(topic_id: Any, body: Any, correct_answer: Any) -> str:
    """Compute a stable SHA256 hash for a question.

    The inputs are normalized: body and correct_answer are stripped, whitespace
    collapsed and lowercased. The topic_id is coerced to string. The hash is
    computed over the concatenation: normalized_body | normalized_correct | topic_id
    """
    nb = _normalize_text(body)
    nc = _normalize_text(correct_answer)
    tid = str(topic_id)
    h = hashlib.sha256()
    h.update(nb.encode("utf-8"))
    h.update(b"|")
    h.update(nc.encode("utf-8"))
    h.update(b"|")
    h.update(tid.encode("utf-8"))
    return h.hexdigest()
