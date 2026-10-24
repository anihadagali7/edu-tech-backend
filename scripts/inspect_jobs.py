import asyncio
import sys
import os

# Ensure repo root is on sys.path so `import app` works when running this script
sys.path.insert(0, os.getcwd())

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.config import get_settings
from app.db.models import LLMJob, Event

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, future=True)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as s:
        print("Last 10 llm_jobs")
        res = await s.execute(select(LLMJob).order_by(LLMJob.created_at.desc()).limit(10))
        rows = res.scalars().all()
        for r in rows:
            print({
                'id': str(r.id),
                'topic_slug': r.topic_slug,
                'status': r.status,
                'created_count': r.created_count,
                'error': r.error,
                'created_at': getattr(r, 'created_at', None),
                'updated_at': getattr(r, 'updated_at', None),
            })

        print('\nRecent events (last 20)')
        res2 = await s.execute(select(Event).order_by(Event.id.desc()).limit(20))
        events = res2.scalars().all()
        for e in events:
            print({'id': str(e.id), 'event_type': e.event_type, 'payload': e.payload})
    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
