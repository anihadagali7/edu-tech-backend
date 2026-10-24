"""API route registration & OpenAPI tags.

Maps to Section 3.1 of the design: API composition with versioned routers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.auth.middleware import clerk_auth_dependency
from app.features.quizzes.router import router as quizzes_router
from app.features.quizzes.sse import router as sse_router
from app.features.topics import router as topics_router
from app.features.llm.jobs import router as llm_jobs_router
from app.features.admin.reporting import router as admin_reporting_router  # NEW
from app.features.profile import router as profile_router
from app.features.learning_content.router import router as learning_content_router
from app.api.routes_study_buddy import include_study_buddy_routes


api = APIRouter()

# User/admin feature routers

api.include_router(quizzes_router)
api.include_router(sse_router)
api.include_router(topics_router)
api.include_router(llm_jobs_router)
api.include_router(admin_reporting_router)  # NEW
api.include_router(profile_router)
api.include_router(learning_content_router, prefix="/learning-content")
include_study_buddy_routes(api)


# Health check endpoint
@api.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "service": "adaptive-quiz-backend"}


# Lean Clerk-backed profile endpoint (no legacy auth routes)
@api.get("/me", tags=["auth"])
async def get_me(_: dict = Depends(clerk_auth_dependency), request: Request = None):
    """Return current principal from Clerk + app_users upsert (id, clerk_user_id, role, name/avatar, org*)."""
    return request.state.user


OPENAPI_TAGS = [
    {"name": "auth", "description": "Authentication (Clerk) & RBAC"},
    {"name": "quizzes", "description": "Quiz lifecycle (start, answer, summary)"},
    {"name": "sse", "description": "Server-Sent Events stream for quiz updates"},
    {"name": "topics", "description": "Published topics, search enqueue, and admin curation"},
    {"name": "learning-materials", "description": "Admin learning materials generation and learner retrieval"},
    {"name": "llm", "description": "LLM job status (user-owned or admin)"},
    {"name": "admin-reporting", "description": "Admin-only reporting and exports"},  # NEW
    {"name": "profile", "description": "User profile management"},
    {"name": "study-buddy", "description": "AI-guided study sessions and hints with SSE"},
]
