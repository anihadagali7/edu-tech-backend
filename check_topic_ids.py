"""Check actual topic ID formats in database."""
import asyncio
from app.db.base import SessionLocal
from app.db.models import Topic
from sqlalchemy import select

async def check_topics():
    async with SessionLocal() as db:
        result = await db.execute(select(Topic).limit(5))
        topics = result.scalars().all()
        
        print("Topics in database:")
        print("-" * 80)
        for t in topics:
            print(f"Name: {t.name}")
            print(f"  id (type): {type(t.id).__name__} = {t.id}")
            print(f"  id (str):  {str(t.id)}")
            print(f"  topic_uid: {t.topic_uid}")
            print()

if __name__ == "__main__":
    asyncio.run(check_topics())
