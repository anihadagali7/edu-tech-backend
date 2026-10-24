import asyncio
from app.db.models import LLMJob
from app.db.base import SessionLocal
from sqlalchemy import select


async def main():
    async with SessionLocal() as session:
        result = await session.execute(
            select(LLMJob).order_by(LLMJob.created_at.desc()).limit(1)
        )
        job = result.scalar_one_or_none()
        if job:
            print(f"Job ID: {job.id}")
            print(f"Job type: {job.job_type}")
            print(f"Job status: {job.status}")
            print(f"Job error: {job.error}")
        else:
            print("No jobs found")


if __name__ == "__main__":
    asyncio.run(main())
