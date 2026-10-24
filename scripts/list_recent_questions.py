import asyncio
import sys
import os
sys.path.insert(0, os.getcwd())
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.config import get_settings
from app.db.models import Question, Topic

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        q = (
            select(Question, Topic.slug)
            .join(Topic, Topic.id == Question.topic_id)
            .order_by(Question.id.desc())
            .limit(50)
        )
        res = await s.execute(q)
        rows = res.all()
        print(f'Found {len(rows)} recent questions (topic_slug, question.body[:80])')
        for question, slug in rows:
            print(slug, question.body[:120])
    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
