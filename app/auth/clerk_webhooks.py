from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert, update, select

from app.db.base import get_session
from app.db.models import AppUser
from app.config import get_settings
import svix

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

@router.post("/clerk")
async def clerk_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """
    Verifies Clerk (Svix) webhook and upserts app_users on user.created/user.updated.
    """
    settings = get_settings()
    payload = await request.body()
    headers = dict(request.headers)
    wh = svix.Webhook(settings.CLERK_WEBHOOK_SECRET or "")
    try:
        msg = wh.verify(payload, headers)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook: {e}")

    event_type: str = msg.get("type", "")
    data: dict = msg.get("data") or {}

    if event_type in ("user.created", "user.updated"):
        clerk_user_id: Optional[str] = data.get("id")
        full_name: Optional[str] = data.get("full_name") or data.get("first_name")
        image_url: Optional[str] = data.get("image_url")
        if not clerk_user_id:
            raise HTTPException(status_code=400, detail="Missing user id in webhook payload")
        await _upsert_app_user(session, clerk_user_id, full_name, image_url)
        return JSONResponse({"ok": True})

    return JSONResponse({"ok": True, "ignored": event_type})

async def _upsert_app_user(session: AsyncSession, clerk_user_id: str, full_name: str | None, avatar_url: str | None):
    row = (await session.execute(select(AppUser.id).where(AppUser.clerk_user_id == clerk_user_id))).first()
    if row:
        await session.execute(
            update(AppUser)
            .where(AppUser.clerk_user_id == clerk_user_id)
            .values(full_name=full_name, avatar_url=avatar_url)
        )
        await session.commit()
        return
    await session.execute(
        insert(AppUser).values(
            clerk_user_id=clerk_user_id,
            full_name=full_name,
            avatar_url=avatar_url,
            role="user",
        )
    )
    await session.commit()