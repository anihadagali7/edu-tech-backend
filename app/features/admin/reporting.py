"""Admin Reporting & Export Endpoints (read-only).

Maps to Section 8.1–8.4 of the design: admin-only user/event listings and small exports.

Routes (all require admin role):
  - GET /admin/users
  - GET /admin/events
  - GET /admin/export.{fmt}   # fmt in {"json","csv"}

Notes:
- Read-only. No persistence changes. No PII beyond email/display_name.
- Pagination: limit (1..200 for list views), offset (>=0).
- Export: limit default 1000 (max 5000).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import clerk_auth_dependency, require_role, require_admin_or_org_admin
from app.auth.schemas import Envelope
from app.db.base import get_session
from app.db.repositories import (
    admin_list_events,
    admin_list_users,
    admin_snapshot_topics,
    count_total_questions
)

router = APIRouter(tags=["admin-reporting"])
log = logging.getLogger("admin.reporting")


# ------------------------ Schemas ------------------------

class PageMeta(BaseModel):
    limit: int
    offset: int
    total: int


class UserRow(BaseModel):
    id: str                       # app_users.id (UUID)
    clerk_user_id: str            # Clerk subject
    full_name: str | None = None
    avatar_url: str | None = None
    role: str | None = None
    profile_complete: bool = False
    age: int | None = None
    highest_education_level: str | None = None
    subjects_of_interest: list[str] = []
    created_at: str | None = None


class UsersListResponse(BaseModel):
    items: list[UserRow]
    limit: int
    offset: int
    total: int


class EventRow(BaseModel):
    id: str
    user_id: str | None = None
    session_id: str | None = None
    event_type: str
    payload: dict[str, Any]
    created_at: str | None = None


class EventsListResponse(BaseModel):
    items: list[EventRow]
    limit: int
    offset: int
    total: int


# ------------------------ Helpers ------------------------

def _csv_from_rows(headers: list[str], rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode("utf-8")


# ------------------------ Endpoints ------------------------

@router.get("/admin/users", response_model=Envelope)
async def admin_users(
    request: Request,
    # user: dict = Depends(require_role("admin")),
    _: dict = Depends(clerk_auth_dependency),
    __: dict = Depends(require_admin_or_org_admin()),
    q: str | None = Query(default=None),
    role: str | None = Query(default=None),
    created_from: str | None = Query(default=None, description="ISO8601"),
    created_to: str | None = Query(default=None, description="ISO8601"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """List users with filters. Email and display_name are searchable."""
    frm_dt = datetime.fromisoformat(created_from) if created_from else None
    to_dt = datetime.fromisoformat(created_to) if created_to else None

    data = await admin_list_users(
        db, q=q, role=role, created_from=frm_dt, created_to=to_dt, limit=limit, offset=offset
    )
    log.info(
        "admin_users_list",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "q": q,
            "role": role,
            "limit": limit,
            "offset": offset,
            "total": data["total"],
        },
    )
    payload = UsersListResponse(
        items=[UserRow(**r) for r in data["items"]],
        limit=limit,
        offset=offset,
        total=data["total"],
    ).model_dump()
    return Envelope(data=payload)


@router.get("/admin/events/count", response_model=Envelope)
async def admin_events_count(
    request: Request,
    _: dict = Depends(clerk_auth_dependency),
    user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Get total count of events."""

    # Get total count by calling admin_list_events with minimal parameters
    data = await admin_list_events(
        db,
        event_type=None,
        user_id=None,
        session_id=None,
        from_ts=None,
        to_ts=None,
        limit=1,
        offset=0,
    )
    
    log.info(
        "admin_events_count",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "total": data["total"],
        },
    )
    
    return Envelope(data={"total": data["total"]})


@router.get("/admin/questions/count", response_model=Envelope)
async def admin_questions_count(
    request: Request,
    _: dict = Depends(clerk_auth_dependency),
    user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """Get total count of questions."""

    total = await count_total_questions(db)
    log.info(
        "admin_questions_count",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "total": total,
        },
    )
    
    return Envelope(data={"total": total})


@router.get("/admin/events", response_model=Envelope)
async def admin_events(
    request: Request,
    # user: dict = Depends(require_role("admin")),
    _: dict = Depends(clerk_auth_dependency), 
    __: dict = Depends(require_admin_or_org_admin()),
    event_type: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    from_ts: str | None = Query(default=None, description="ISO8601"),
    to_ts: str | None = Query(default=None, description="ISO8601"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """List audit events with optional filters and pagination."""
    frm = datetime.fromisoformat(from_ts) if from_ts else None
    to = datetime.fromisoformat(to_ts) if to_ts else None

    uid = UUID(user_id) if user_id else None
    sid = UUID(session_id) if session_id else None

    data = await admin_list_events(
        db,
        event_type=event_type,
        user_id=uid,
        session_id=sid,
        from_ts=frm,
        to_ts=to,
        limit=limit,
        offset=offset,
    )

    log.info(
        "admin_events_list",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "event_type": event_type,
            "user_id": user_id,
            "session_id": session_id,
            "limit": limit,
            "offset": offset,
            "total": data["total"],
        },
    )

    payload = EventsListResponse(
        items=[EventRow(**r) for r in data["items"]],
        limit=limit,
        offset=offset,
        total=data["total"],
    ).model_dump()
    return Envelope(data=payload)


@router.get("/admin/export.{fmt}")
async def admin_export(
    request: Request,
    fmt: Literal["json", "csv"],
    _: dict = Depends(clerk_auth_dependency),
    __: dict = Depends(require_admin_or_org_admin()),
    type: Literal["users", "topics", "events"] = Query(..., alias="type"),
    include_unpublished: bool = Query(default=False, description="For topics export only"),
    limit: int = Query(default=1000, ge=1, le=5000),
    # Optional filters mirrored from list endpoints:
    q: str | None = Query(default=None, description="Users filter"),
    role: str | None = Query(default=None, description="Users filter"),
    created_from: str | None = Query(default=None, description="Users ISO8601"),
    created_to: str | None = Query(default=None, description="Users ISO8601"),
    event_type: str | None = Query(default=None, description="Events filter"),
    user_id: str | None = Query(default=None, description="Events filter"),
    session_id: str | None = Query(default=None, description="Events filter"),
    from_ts: str | None = Query(default=None, description="Events ISO8601"),
    to_ts: str | None = Query(default=None, description="Events ISO8601"),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Small exports in JSON or CSV format (in-memory, bounded)."""
    # Collect rows according to the export type
    if type == "users":
        frm_dt = datetime.fromisoformat(created_from) if created_from else None
        to_dt = datetime.fromisoformat(created_to) if created_to else None
        res = await admin_list_users(db, q=q, role=role, created_from=frm_dt, created_to=to_dt, limit=limit, offset=0)
        rows = res["items"]
        # Note: role removed from headers - roles are managed by Clerk, not stored in DB
        headers = ["id", "clerk_user_id", "full_name", "avatar_url", "profile_complete", "age", "highest_education_level", "subjects_of_interest", "created_at"]
    elif type == "topics":
        rows = await admin_snapshot_topics(db, include_unpublished=include_unpublished)
        # cap rows for export
        rows = rows[:limit]
        headers = ["id", "name", "slug", "description", "is_published", "created_at", "updated_at"]
    else:  # events
        uid = UUID(user_id) if user_id else None
        sid = UUID(session_id) if session_id else None
        frm = datetime.fromisoformat(from_ts) if from_ts else None
        to = datetime.fromisoformat(to_ts) if to_ts else None
        res = await admin_list_events(
            db,
            event_type=event_type,
            user_id=uid,
            session_id=sid,
            from_ts=frm,
            to_ts=to,
            limit=limit,
            offset=0,
        )
        rows = res["items"]
        headers = ["id", "user_id", "session_id", "event_type", "payload", "created_at"]

    log.info(
        "admin_export",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "fmt": fmt,
            "type": type,
            "count": len(rows),
        },
    )

    if fmt == "json":
        # Reuse envelope for consistency
        return JSONResponse(content={"success": True, "data": rows})
    # CSV
    body = _csv_from_rows(headers, rows)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{type}.csv"'},
    )
