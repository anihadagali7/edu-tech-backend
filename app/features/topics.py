"""Topics & Search API (user + admin).

Maps to Section 6.1–6.4 of the design: topic listing, search enqueue,
admin curation (CRUD), and bulk question import.

Routes (user):
  - GET /topics
  - GET /topics/{id}
  - GET /search?q=...

Routes (admin; RBAC: admin only):
  - POST   /admin/topics
  - PATCH  /admin/topics/{id}
  - DELETE /admin/topics/{id}
  - POST   /admin/questions/import
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query, Request, status
from pydantic import BaseModel, Field
from slugify import slugify
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import clerk_auth_dependency, require_role, require_admin_or_org_admin
from app.auth.schemas import Envelope
from app.db.base import get_session
from app.db.models import Event
from app.db.repositories import (
    ImportItem,
    admin_create_topic,
    admin_delete_topic,
    admin_update_topic,
    bulk_upsert_questions,
    count_questions_by_topic,
    get_topic_by_id,
    get_topic_by_slug,
    list_topics as repo_list_topics,
    upsert_pending_topic_and_job,
)
from sqlalchemy import select
from app.utils.errors import AppError, TOP404_NOT_FOUND, TOP409_DUPLICATE_SLUG

router = APIRouter(tags=["topics"])
log = logging.getLogger("topics")


# -------------------------- Schemas --------------------------

class TopicOut(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None = None
    is_published: bool
    question_count: int = 0


class TopicSummary(BaseModel):
    topic: TopicOut


class TopicsListResponse(BaseModel):
    items: List[TopicOut]
    limit: int
    offset: int
    total: int


class TopicCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: Optional[str] = Field(default=None, description="Slug (if omitted, derived from name)")
    description: Optional[str] = None
    is_published: bool = False


class TopicUpdateRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    is_published: Optional[bool] = None


class ImportQuestionItemModel(BaseModel):
    body: str
    choices: dict
    correct_answer: str
    difficulty: int = Field(ge=1, le=5)
    question_hash: str


class ImportQuestionsRequest(BaseModel):
    topic_id: str
    items: List[ImportQuestionItemModel]


class SearchResponse(BaseModel):
    matches: List[TopicOut]
    enqueued: dict | None = None


# -------------------------- User endpoints --------------------------


@router.get("/topics", response_model=Envelope, dependencies=[Depends(clerk_auth_dependency)])
async def list_topics(
    request: Request,
    q: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """List **published** topics with optional fuzzy search."""
    result = await repo_list_topics(db, q=q, published_only=True, limit=limit, offset=offset)
    rows = result["items"]
    total = result["total"]
    
    # Fetch question counts for each topic
    items = []
    for r in rows:
        count = await count_questions_by_topic(db, UUID(r.id))
        items.append(
            TopicOut(
                id=r.id,
                name=r.name,
                slug=r.slug,
                description=r.description,
                is_published=r.is_published,
                question_count=count,
            )
        )
    
    data = TopicsListResponse(
        items=items,
        limit=limit,
        offset=offset,
        total=total,
    ).model_dump()
    log.info(
        "topics_list",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "q": q,
            "limit": limit,
            "offset": offset,
            "count": len(rows),
        },
    )
    return Envelope(data=data)


@router.get("/topics/{id}", response_model=Envelope, dependencies=[Depends(clerk_auth_dependency)])
async def get_topic(
    request: Request,
    id: str = Path(..., description="Topic UUID"),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Return a topic summary by id; 404 if not found or soft-deleted."""
    topic = await get_topic_by_id(db, UUID(id))
    if not topic or not topic.is_published:
        raise AppError("topic not found", code=TOP404_NOT_FOUND, status=404)

    count = await count_questions_by_topic(db, UUID(topic.id))
    data = TopicSummary(
        topic=TopicOut(
            id=topic.id,
            name=topic.name,
            slug=topic.slug,
            description=topic.description,
            is_published=topic.is_published,
            question_count=count,
        ),
    ).model_dump()
    log.info(
        "topic_get",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "topic_id": topic.id,
            "slug": topic.slug,
            "question_count": count,
        },
    )
    return Envelope(data=data)


@router.get("/search", response_model=Envelope, dependencies=[Depends(clerk_auth_dependency)])
async def search(
    request: Request,
    q: str = Query(..., min_length=1),
    principal: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Search topics by query; ask for confirmation if no published match found.

    Guardrails:
      - only show confirmation if normalized slug has length >= 3 characters.
    """
    # First try to find published matches
    matches_result = await repo_list_topics(db, q=q, published_only=True, limit=20, offset=0)
    matches_rows = matches_result["items"]
    matches = []
    for r in matches_rows:
        count = await count_questions_by_topic(db, UUID(r.id))
        matches.append(
            TopicOut(
                id=r.id,
                name=r.name,
                slug=r.slug,
                description=r.description,
                is_published=r.is_published,
                question_count=count,
            )
        )
    if matches:
        return Envelope(data=SearchResponse(matches=matches, enqueued=None).model_dump())

    # Guardrails: require at least 3 chars in slug
    slug = slugify(q or "")
    if len(slug) < 3:
        return Envelope(data=SearchResponse(matches=[], enqueued=None).model_dump())

    # Check if already requested
    from app.db.models import PendingTopic
    
    existing_stmt = select(PendingTopic).where(PendingTopic.topic_slug == slug)
    existing_result = await db.execute(existing_stmt)
    existing_pending = existing_result.scalar_one_or_none()
    
    if existing_pending:
        # Already requested, return message
        return Envelope(data={
            "matches": [], 
            "message": "This topic has already been requested and is pending admin review.",
            "topic_slug": slug,
            "status": "already_requested"
        })
    
    # No matches found and not already requested - ask for confirmation
    return Envelope(data={
        "matches": [], 
        "message": f"No topics found for '{q}'. Would you like to submit a request for this topic to be created?",
        "topic_slug": slug,
        "topic_name": q.strip(),
        "status": "confirmation_needed",
        "confirmation_required": True
    })


@router.post("/request-topic", response_model=Envelope, dependencies=[Depends(clerk_auth_dependency)])
async def request_topic_creation(
    request: Request,
    topic_name: str = Body(..., embed=True),
    principal: dict = Depends(clerk_auth_dependency),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Submit a confirmed request for topic creation."""
    
    # Guardrails: require at least 3 chars in slug
    slug = slugify(topic_name or "")
    if len(slug) < 3:
        return Envelope(
            data={"error": "Topic name too short"},
            success=False
        )

    from app.db.models import PendingTopic
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    
    # Check if already requested (double-check)
    existing_stmt = select(PendingTopic).where(PendingTopic.topic_slug == slug)
    existing_result = await db.execute(existing_stmt)
    existing_pending = existing_result.scalar_one_or_none()
    
    if existing_pending:
        return Envelope(data={
            "message": "This topic has already been requested and is pending admin review.",
            "topic_slug": slug,
            "status": "already_requested"
        })
    
    # Create new pending topic request
    pending_topic = PendingTopic(
        topic_slug=slug,
        display_name=topic_name.strip(),
        status="queued",
        requested_by=principal["id"]
    )
    
    db.add(pending_topic)
    await db.commit()

    # Emit event for topic request
    await db.execute(
        pg_insert(Event).values(
            user_id=principal["id"],
            session_id=None,  # System event
            event_type="TOPIC_REQUESTED",
            payload={"query": topic_name, "topic_slug": slug, "pending_id": str(pending_topic.id)},
        )
    )
    await db.commit()

    log.info(
        "topic_requested",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "user_id": principal["id"],
            "topic_name": topic_name,
            "slug": slug,
            "pending_id": str(pending_topic.id),
        },
    )

    return Envelope(data={
        "message": "Your topic request has been sent to administrators for review. You will be notified when the topic is available.",
        "topic_slug": slug,
        "status": "request_submitted",
        "pending_id": str(pending_topic.id)
    })


# -------------------------- Admin endpoints --------------------------


@router.post("/admin/topics", response_model=Envelope, tags=["admin"], status_code=status.HTTP_201_CREATED)
async def admin_create(
    req: TopicCreateRequest,
    request: Request,
    # user: dict = Depends(require_role("admin")),
    _: dict = Depends(clerk_auth_dependency),
    __: dict = Depends(require_admin_or_org_admin()),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Create a curated topic (admin-only)."""
    slug = req.slug or slugify(req.name)
    row = await admin_create_topic(db, name=req.name, slug=slug, description=req.description, is_published=req.is_published)

    await db.execute(
        pg_insert(Event).values(
            event_type="TOPIC_CREATED",
            user_id=None,  # filled by middleware in future if needed
            payload={"topic_id": row.id, "slug": row.slug, "name": row.name, "is_published": row.is_published},
        )
    )
    await db.commit()

    log.info(
        "topic_created",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "topic_id": row.id,
            "slug": row.slug,
            "published": row.is_published,
        },
    )

    return Envelope(data=TopicOut(**row.__dict__).model_dump())


@router.patch("/admin/topics/{id}", response_model=Envelope, tags=["admin"])
async def admin_update(
    req: TopicUpdateRequest,
    request: Request,
    id: str = Path(..., description="Topic UUID"),
    # user: dict = Depends(require_role("admin")),
    _: dict = Depends(clerk_auth_dependency),
    __: dict = Depends(require_admin_or_org_admin()),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Update a topic (admin-only). Allows toggling `is_published`."""
    row = await admin_update_topic(
        db,
        topic_id=UUID(id),
        name=req.name,
        slug=slugify(req.slug) if req.slug is not None else None,
        description=req.description,
        is_published=req.is_published,
    )

    evt_type = "TOPIC_UPDATED"
    if req.is_published is not None:
        evt_type = "TOPIC_PUBLISHED" if req.is_published else "TOPIC_UNPUBLISHED"

    await db.execute(
        pg_insert(Event).values(
            event_type=evt_type,
            payload={"topic_id": row.id, "slug": row.slug, "name": row.name, "is_published": row.is_published},
        )
    )
    await db.commit()

    log.info(
        "topic_updated",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "topic_id": row.id,
            "slug": row.slug,
            "published": row.is_published,
        },
    )

    return Envelope(data=TopicOut(**row.__dict__).model_dump())


@router.delete("/admin/topics/{id}", response_model=Envelope, tags=["admin"], status_code=status.HTTP_200_OK)
async def admin_delete(
    request: Request,
    id: str = Path(..., description="Topic UUID"),
    soft: bool = Query(default=True, description="Soft delete when true"),
    # user: dict = Depends(require_role("admin")),
    _: dict = Depends(clerk_auth_dependency),
    __: dict = Depends(require_admin_or_org_admin()),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Delete or soft delete a topic (admin-only)."""
    await admin_delete_topic(db, topic_id=UUID(id), soft=soft)

    await db.execute(
        pg_insert(Event).values(event_type="TOPIC_DELETED", payload={"topic_id": id, "soft": soft})
    )
    await db.commit()

    log.info(
        "topic_deleted",
        extra={"request_id": getattr(request.state, "request_id", None), "topic_id": id, "soft": soft},
    )
    return Envelope(data={"deleted": True, "soft": soft})


@router.post("/admin/questions/import", response_model=Envelope, tags=["admin"])
async def admin_import_questions(
    req: ImportQuestionsRequest,
    request: Request,
    # user: dict = Depends(require_role("admin")),
    _: dict = Depends(clerk_auth_dependency),
    __: dict = Depends(require_admin_or_org_admin()),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Bulk upsert questions for a topic by `question_hash` (admin-only)."""
    topic = await get_topic_by_id(db, UUID(req.topic_id), include_deleted=False)
    if not topic:
        raise AppError("topic not found", code=TOP404_NOT_FOUND, status=404)

    items = [ImportItem(**i.model_dump()) for i in req.items]
    result = await bulk_upsert_questions(db, topic_id=UUID(topic.id), items=items)

    await db.execute(
        pg_insert(Event).values(
            event_type="QUESTIONS_IMPORTED",
            payload={"topic_id": topic.id, "created": result["created_count"], "duplicates": result["duplicate_count"]},
        )
    )
    await db.commit()

    log.info(
        "questions_imported",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "topic_id": topic.id,
            "created": result["created_count"],
            "duplicates": result["duplicate_count"],
        },
    )

    return Envelope(data=result)