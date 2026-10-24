#!/usr/bin/env python3
"""Retry a failed LLM job.

Usage:
    python scripts/retry_failed_job.py <job_id>
    python scripts/retry_failed_job.py --all-failed
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import argparse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import get_settings
from app.db.models import LLMJob


async def retry_job(job_id: str):
    """Reset a failed job back to queued status."""
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with SessionLocal() as db:
        # Find the job
        result = await db.execute(
            select(LLMJob).where(LLMJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        
        if not job:
            print(f"❌ Job {job_id} not found")
            return False
        
        if job.status != "failed":
            print(f"⚠️  Job {job_id} is {job.status}, not failed")
            return False
        
        # Reset to queued
        await db.execute(
            update(LLMJob)
            .where(LLMJob.id == job_id)
            .values(status="queued", error=None, retry_count=0)
        )
        await db.commit()
        
        print(f"✅ Job {job_id} ({job.topic_slug}) reset to queued")
        return True
    
    await engine.dispose()


async def retry_all_failed():
    """Reset all failed jobs back to queued."""
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with SessionLocal() as db:
        # Find all failed jobs
        result = await db.execute(
            select(LLMJob).where(LLMJob.status == "failed")
        )
        failed_jobs = result.scalars().all()
        
        if not failed_jobs:
            print("ℹ️  No failed jobs found")
            return 0
        
        print(f"Found {len(failed_jobs)} failed jobs:")
        for job in failed_jobs:
            print(f"  - {job.id} ({job.topic_slug}): {job.error[:100] if job.error else 'no error'}...")
        
        # Reset all to queued
        await db.execute(
            update(LLMJob)
            .where(LLMJob.status == "failed")
            .values(status="queued", error=None, retry_count=0)
        )
        await db.commit()
        
        print(f"\n✅ Reset {len(failed_jobs)} jobs to queued")
        return len(failed_jobs)
    
    await engine.dispose()


async def main():
    parser = argparse.ArgumentParser(description="Retry failed LLM jobs")
    parser.add_argument("job_id", nargs="?", help="Specific job ID to retry")
    parser.add_argument("--all-failed", action="store_true", help="Retry all failed jobs")
    
    args = parser.parse_args()
    
    if args.all_failed:
        count = await retry_all_failed()
        return 0 if count >= 0 else 1
    elif args.job_id:
        success = await retry_job(args.job_id)
        return 0 if success else 1
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
