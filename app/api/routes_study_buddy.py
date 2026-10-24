# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""API router aggregation for Study Buddy and learning materials endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.features.learning_content import ENABLE_LEARNING_MATERIALS
from app.features.learning_content.router import router as learning_router
from app.features.study_buddy import ENABLE_STUDY_BUDDY
from app.features.study_buddy.router import router as study_router
from app.features.study_buddy.sse import router as study_sse_router

api_router = APIRouter()

_STUDY_BUDDY_MOUNTED = False
_LEARNING_MOUNTED = False


def include_study_buddy_routes(root_router: APIRouter) -> None:
    """Attach Study Buddy and learning material routers when feature flags permit."""

    global _STUDY_BUDDY_MOUNTED, _LEARNING_MOUNTED

    if ENABLE_STUDY_BUDDY and not _STUDY_BUDDY_MOUNTED:
        root_router.include_router(study_router)
        root_router.include_router(study_sse_router)
        _STUDY_BUDDY_MOUNTED = True

    if ENABLE_LEARNING_MATERIALS and not _LEARNING_MOUNTED:
        root_router.include_router(learning_router)
        _LEARNING_MOUNTED = True
