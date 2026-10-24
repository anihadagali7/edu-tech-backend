# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""Learning content feature package initialization and feature flags."""

from __future__ import annotations

import os


def _env_flag(name: str, default: bool = False) -> bool:
	value = os.getenv(name)
	if value is None:
		return default
	return value.strip().lower() in {"1", "true", "yes", "on"}


ENABLE_LEARNING_MATERIALS: bool = _env_flag("ENABLE_LEARNING_MATERIALS", default=False)
"""Feature flag controlling access to learning material generation endpoints."""
