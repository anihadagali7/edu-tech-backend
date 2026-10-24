# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""Study Buddy feature package initialization and shared constants."""

from __future__ import annotations

import os


def _env_flag(name: str, default: bool = False) -> bool:
	value = os.getenv(name)
	if value is None:
		return default
	return value.strip().lower() in {"1", "true", "yes", "on"}


ENABLE_STUDY_BUDDY: bool = _env_flag("ENABLE_STUDY_BUDDY", default=False)
"""Feature flag for enabling Study Buddy endpoints and background jobs."""
