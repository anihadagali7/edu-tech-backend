# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""Enumerations for LLM worker job types including Study Buddy workloads."""

from __future__ import annotations

from enum import Enum


class LLMJobType(str, Enum):
    """Job type constants coordinating API requests, worker handlers, and analytics pipelines.

    TODO:
    1. Align enum member names with existing worker queue naming conventions.
    2. Document mapping between enum values and handler modules for clarity.
    3. Provide helper methods for scheduling priorities or feature flag checks.

    Acceptance:
    - Enum values match queue identifiers expected by worker runner.
    - Adding new job types requires minimal code changes elsewhere.
    - Works with JSON serialization for job payloads.
    """

    LEARNING_MATERIAL_GENERATION = "learning_material_generation"
    STUDY_BUDDY_REPLY = "study_buddy_reply"
    STUDY_SESSION_SUMMARY = "study_session_summary"
