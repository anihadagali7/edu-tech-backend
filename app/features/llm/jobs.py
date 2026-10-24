"""LLM job management for topic generation.

Provides job enqueuing, status tracking, and admin interfaces for managing
LLM-generated educational content.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import clerk_auth_dependency, require_role
from app.auth.schemas import Envelope
from app.db.base import get_session
from app.db.models import LLMJob, PendingTopic
from app.features.llm.auto_worker import trigger_worker_async

router = APIRouter(prefix="/llm", tags=["llm"])
log = logging.getLogger("llm.jobs")


# ------------------------ Schemas ------------------------

class JobParams(BaseModel):
    """Parameters for LLM job generation."""
    batch_size: int = Field(default=15, ge=1, le=100, description="Number of questions to generate")
    language: str = Field(default="en", description="Language code (en, es, fr, etc.)")
    topic_hint_description: str = Field(default="", description="Additional context for the topic")
    avoid_phrases: List[str] = Field(default_factory=list, description="Phrases to avoid in questions")


class TopicRequestCreate(BaseModel):
    """Request to create a new topic via LLM generation."""
    topic_name: str = Field(..., min_length=2, max_length=200, description="Display name for the topic")
    topic_description: str = Field(..., min_length=10, max_length=1000, description="Description of the topic")
    params: JobParams = Field(default_factory=JobParams, description="Generation parameters")


class JobStatus(BaseModel):
    """LLM job status information."""
    id: str
    job_type: str
    status: str
    topic_slug: Optional[str]
    topic_name: Optional[str]
    created_count: Optional[int]
    error: Optional[str]
    created_at: str
    updated_at: str


class PendingTopicRequest(BaseModel):
    """Pending topic request from users."""
    id: str
    topic_slug: str
    display_name: Optional[str]
    status: str
    requested_by: Optional[str]
    created_at: str


class JobsListResponse(BaseModel):
    """Response for jobs listing."""
    jobs: List[JobStatus]
    total: int
    limit: int
    offset: int


class PendingRequestsResponse(BaseModel):
    """Response for pending topic requests."""
    requests: List[PendingTopicRequest]
    total: int
    total_queued: int  # Count of items with status="queued" (for badge)
    limit: int
    offset: int


# ------------------------ Public endpoints ------------------------

@router.get("/health")
async def llm_health():
    """Health check for LLM module."""
    return {"ok": True, "module": "llm"}


# ------------------------ Admin endpoints ------------------------

@router.get("/admin/pending-requests", response_model=Envelope, tags=["admin"])
async def list_pending_requests(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(clerk_auth_dependency),
    principal: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """List all pending topic requests (queued, approved, rejected)."""
    
    # Count total queued requests (for pending badge)
    count_stmt = select(func.count()).select_from(PendingTopic).where(PendingTopic.status == "queued")
    total_queued_result = await db.execute(count_stmt)
    total_queued = total_queued_result.scalar() or 0
    
    # Get all pending requests (including approved/rejected for history)
    stmt = (
        select(PendingTopic)
        .order_by(desc(PendingTopic.created_at))
        .limit(limit)
        .offset(offset)
    )
    
    result = await db.execute(stmt)
    pending_requests = result.scalars().all()
    
    requests_data = [
        PendingTopicRequest(
            id=str(req.id),
            topic_slug=req.topic_slug,
            display_name=req.display_name,
            status=req.status,
            requested_by=str(req.requested_by) if req.requested_by else None,
            created_at=req.created_at.isoformat(),
        )
        for req in pending_requests
    ]
    
    # Total count of all requests
    count_all_stmt = select(func.count()).select_from(PendingTopic)
    total_all_result = await db.execute(count_all_stmt)
    total_all = total_all_result.scalar() or 0
    
    return Envelope(
        data=PendingRequestsResponse(
            requests=requests_data,
            total=total_all,
            total_queued=total_queued,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.post("/admin/approve-topic", response_model=Envelope, tags=["admin"], status_code=status.HTTP_201_CREATED)
async def approve_topic_request(
    req: TopicRequestCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    _: dict = Depends(clerk_auth_dependency),
    principal: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Admin approves a topic request and enqueues LLM job. Worker runs automatically."""
    
    from slugify import slugify
    
    # Generate slug from topic name
    topic_slug = slugify(req.topic_name)
    if len(topic_slug) < 3:
        raise HTTPException(
            status_code=400,
            detail="Topic name must generate a slug with at least 3 characters"
        )
    
    # Create LLM job with admin-provided details
    job = LLMJob(
        job_type="generate_topic",
        status="queued",
        topic_slug=topic_slug,
        topic_name=req.topic_name,
        params={
            "batch_size": req.params.batch_size,
            "language": req.params.language,
            "topic_hint_description": req.topic_description,  # Use full description
            "avoid_phrases": req.params.avoid_phrases,
        },
        requested_by=principal["id"],
    )
    
    db.add(job)
    await db.commit()
    await db.refresh(job)
    
    # Remove from pending requests if it exists
    await db.execute(
        select(PendingTopic)
        .where(PendingTopic.topic_slug == topic_slug)
        .where(PendingTopic.status == "queued")
    )
    
    # Update pending topic status to approved
    from sqlalchemy import update
    await db.execute(
        update(PendingTopic)
        .where(PendingTopic.topic_slug == topic_slug)
        .values(status="approved")
    )
    await db.commit()
    
    # Trigger automatic worker processing in background
    background_tasks.add_task(trigger_worker_async, str(job.id))
    
    log.info(
        "topic_approved",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "admin_id": principal["id"],
            "topic_slug": topic_slug,
            "job_id": str(job.id),
        },
    )
    
    return Envelope(
        data={
            "job_id": str(job.id),
            "topic_slug": topic_slug,
            "topic_name": req.topic_name,
            "status": "queued",
            "message": "Topic approved and queued for generation. Worker processing automatically."
        }
    )


@router.post("/admin/create-topic", response_model=Envelope, tags=["admin"])
async def admin_create_topic(
    req: TopicRequestCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    _: dict = Depends(clerk_auth_dependency),
    principal: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """
    Admin directly creates a topic (bypasses pending approval flow).
    If topic already exists, adds more questions to it.
    Default: 30 questions per job run.
    Worker processes automatically in background.
    """
    
    from slugify import slugify
    from app.db.models import Topic
    
    # Generate slug from topic name
    topic_slug = slugify(req.topic_name)
    if len(topic_slug) < 3:
        raise HTTPException(
            status_code=400,
            detail="Topic name must generate a slug with at least 3 characters"
        )
    
    # Check if topic already exists
    existing_topic = await db.execute(
        select(Topic).where(Topic.slug == topic_slug)
    )
    topic_exists = existing_topic.scalar_one_or_none() is not None
    
    # Set batch size to 30 if not specified
    batch_size = req.params.batch_size if req.params.batch_size != 15 else 30
    
    # Create LLM job
    job = LLMJob(
        job_type="generate_topic",
        status="queued",
        topic_slug=topic_slug,
        topic_name=req.topic_name,
        params={
            "batch_size": batch_size,
            "language": req.params.language,
            "topic_hint_description": req.topic_description,
            "avoid_phrases": req.params.avoid_phrases,
            "append_to_existing": topic_exists,  # Signal to worker to append questions
        },
        requested_by=principal["id"],
    )
    
    db.add(job)
    await db.commit()
    await db.refresh(job)
    
    # Trigger automatic worker processing in background
    background_tasks.add_task(trigger_worker_async, str(job.id))
    
    log.info(
        "admin_topic_created",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "admin_id": principal["id"],
            "topic_slug": topic_slug,
            "job_id": str(job.id),
            "existing_topic": topic_exists,
            "batch_size": batch_size,
        },
    )
    
    message = (
        f"Adding {batch_size} more questions to existing topic '{req.topic_name}'. Processing automatically in background."
        if topic_exists
        else f"Creating new topic '{req.topic_name}' with {batch_size} questions. Processing automatically in background."
    )
    
    return Envelope(
        data={
            "job_id": str(job.id),
            "topic_slug": topic_slug,
            "topic_name": req.topic_name,
            "status": "queued",
            "batch_size": batch_size,
            "existing_topic": topic_exists,
            "message": message,
        }
    )


@router.get("/admin/jobs", response_model=Envelope, tags=["admin"])
async def list_jobs(
    request: Request,
    status_filter: Optional[str] = Query(None, description="Filter by job status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(clerk_auth_dependency),
    principal: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """List LLM jobs with optional status filtering."""
    
    # Build query
    stmt = select(LLMJob)
    
    if status_filter:
        stmt = stmt.where(LLMJob.status == status_filter)
    
    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Get jobs
    stmt = stmt.order_by(desc(LLMJob.updated_at)).limit(limit).offset(offset)
    result = await db.execute(stmt)
    jobs = result.scalars().all()
    
    jobs_data = [
        JobStatus(
            id=str(job.id),
            job_type=job.job_type,
            status=job.status,
            topic_slug=job.topic_slug,
            topic_name=job.topic_name,
            created_count=job.created_count,
            error=job.error,
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
        )
        for job in jobs
    ]
    
    return Envelope(
        data=JobsListResponse(
            jobs=jobs_data,
            total=total,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.post("/admin/pending-requests/{request_id}/reject", response_model=Envelope, tags=["admin"])
async def reject_topic_request(
    request_id: str,
    request: Request,
    _: dict = Depends(clerk_auth_dependency),
    principal: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Admin rejects a pending topic request. Sets status to 'rejected'."""
    
    # Find the pending request
    stmt = select(PendingTopic).where(PendingTopic.id == UUID(request_id))
    result = await db.execute(stmt)
    pending_request = result.scalar_one_or_none()
    
    if not pending_request:
        raise HTTPException(status_code=404, detail="Pending request not found")
    
    # Update status to rejected
    from sqlalchemy import update
    await db.execute(
        update(PendingTopic)
        .where(PendingTopic.id == UUID(request_id))
        .values(status="rejected")
    )
    await db.commit()
    
    log.info(
        "topic_rejected",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "admin_id": principal["id"],
            "topic_slug": pending_request.topic_slug,
            "pending_request_id": request_id,
        },
    )
    
    return Envelope(
        data={
            "rejected": True,
            "status": "rejected",
            "topic_slug": pending_request.topic_slug,
        }
    )


# ------------------------ Helper functions ------------------------

async def enqueue_generate_topic(
    session: AsyncSession, *, topic_slug: str, topic_name: str, params: dict, requested_by: UUID | None
) -> UUID:
    """Create a pending LLM job for topic generation."""
    job = LLMJob(
        job_type="generate_topic",
        status="queued",
        topic_slug=topic_slug,
        topic_name=topic_name,
        params=params,
        requested_by=requested_by,
    )
    
    session.add(job)
    await session.commit()
    await session.refresh(job)
    
    return job.id


async def get_job_status(session: AsyncSession, job_id: UUID) -> JobStatus | None:
    """Get status of a specific job."""
    stmt = select(LLMJob).where(LLMJob.id == job_id)
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    
    if not job:
        return None
    
    return JobStatus(
        id=str(job.id),
        job_type=job.job_type,
        status=job.status,
        topic_slug=job.topic_slug,
        topic_name=job.topic_name,
        created_count=job.created_count,
        error=job.error,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )
