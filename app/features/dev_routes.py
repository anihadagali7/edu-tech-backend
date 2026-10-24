"""Development-only test endpoints without auth - DO NOT USE IN PRODUCTION"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import Envelope
from app.db.base import get_session
from app.db.repositories import list_topics as repo_list_topics
from app.features.topics import TopicOut, TopicsListResponse

router = APIRouter(prefix="/dev", tags=["dev"])

@router.get("/topics-noauth")
async def dev_list_topics(
    db: AsyncSession = Depends(get_session),
) -> Envelope:
    """DEV ONLY: List topics without authentication."""
    rows = await repo_list_topics(db, q=None, published_only=True, limit=50, offset=0)
    data = TopicsListResponse(
        items=[
            TopicOut(
                id=r.id,
                name=r.name,
                slug=r.slug,
                description=r.description,
                is_published=r.is_published,
            )
            for r in rows
        ],
        limit=50,
        offset=0,
    ).model_dump()
    return Envelope(data=data)
