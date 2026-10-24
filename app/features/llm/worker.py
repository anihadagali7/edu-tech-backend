"""LLM worker runner for processing queued topic generation jobs.

This module processes LLM jobs by:
1. Claiming queued jobs atomically
2. Calling OpenAI via LangChain with structured prompts
3. Validating JSON responses with Pydantic
4. Upserting topics and questions with deduplication
5. Emitting events and updating job status

Usage:
    python -m app.features.llm.worker  # Process jobs
"""


from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import traceback
from uuid import UUID
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional, Iterable
from dataclasses import dataclass

from pydantic import ValidationError
import sqlalchemy as sa
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from slugify import slugify
from tenacity import retry, wait_random_exponential, stop_after_attempt

from app.db.base import get_session
from app.db.models import Event, LLMJob, PendingTopic, Question, Topic
from app.features.llm.schema import LLMTopicArtifact, QuestionArtifact, QuestionUpsertResult
from app.db.repositories import ImportItem, bulk_upsert_questions
from app.utils.qhash import compute_question_hash

# Type aliases for compatibility
QuestionItem = QuestionArtifact
TopicQuestionsArtifact = LLMTopicArtifact
from app.config import get_settings

log = logging.getLogger("worker")


# ----------------------------- Helpers -----------------------------


def _normalize_text(s: str) -> str:
    return " ".join(s.strip().split()).lower()


def _compute_question_hash(topic_id: UUID, item: QuestionArtifact) -> str:
    """Wrapper to the shared compute_question_hash util."""
    return compute_question_hash(topic_id, item.body, item.correct_answer)


async def _ensure_topic_for_slug(db: AsyncSession, *, slug: str, display_name: Optional[str]) -> Topic:
    """Idempotently ensure a Topic exists for slug."""
    row = (await db.execute(select(Topic).where(Topic.slug == slug))).scalar_one_or_none()
    if row:
        return row
    ins = (
        pg_insert(Topic)
        .values(name=display_name or slug.replace("-", " ").title(), slug=slug, description=None, is_published=False, is_deleted=False)
        .on_conflict_do_nothing(index_elements=[Topic.slug])
        .returning(Topic.id)
    )
    res = await db.execute(ins)
    rid = res.scalar_one_or_none()
    if rid:
        return (await db.execute(select(Topic).where(Topic.id == rid))).scalar_one()
    # if concurrent insert won
    return (await db.execute(select(Topic).where(Topic.slug == slug))).scalar_one()


async def _claim_oldest_job(db: AsyncSession) -> Optional[LLMJob]:
    """Claim the oldest queued job and mark it running; return the row."""
    # Lock a queued job deterministically
    sub = (
        select(LLMJob.id)
        .where(LLMJob.status == "queued")
        .order_by(LLMJob.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = (await db.execute(select(LLMJob).where(LLMJob.id == sub.scalar_subquery()).with_for_update())).scalar_one_or_none()
    if not job:
        return None

    await db.execute(sa.update(LLMJob).where(LLMJob.id == job.id).values(status="running", error=None))
    await db.execute(pg_insert(Event).values(event_type="LLM_JOB_RUNNING", payload={"job_id": str(job.id), "topic_slug": job.topic_slug}))
    return job


@retry(wait=wait_random_exponential(multiplier=1, max=10), stop=stop_after_attempt(3))
async def _call_llm_generate(*, topic_slug: str, n: int = 20, topic_name: str = None, topic_description: str = None) -> dict:
    """Provider-agnostic wrapper used by the worker.

    - Delegates to the configured provider via env `LLM_PROVIDER`.
    - Retries are handled by the decorator (only around the provider call).
    """
    provider = (os.getenv("LLM_PROVIDER") or "").lower()

    if provider == "openai":
        # Lazy import so the API server doesn't require the extra.
        from app.features.llm.provider_openai import generate_questions  # local import
        # Validate minimal env presence (the OpenAI SDK will also check)
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set for LLM_PROVIDER=openai")
        return await generate_questions(
            topic_slug=topic_slug, 
            n=n, 
            topic_name=topic_name, 
            topic_description=topic_description
        )


def _maybe_upload_s3(*, bucket: str | None, key: str, data: bytes) -> str | None:
    """Upload artifact to S3 if boto3 is available and bucket provided. Best-effort."""
    if not bucket:
        return None
    try:
        import boto3  # type: ignore
    except Exception:
        return None
    try:
        s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/json")
        return f"s3://{bucket}/{key}"
    except Exception as e:  # best-effort
        log.warning("s3_upload_failed", extra={"error": str(e), "key": key})
        return None


def _items_to_import(topic_id: UUID, items: Iterable[QuestionArtifact]) -> list[ImportItem]:
    rows: list[ImportItem] = []
    for it in items:
        rows.append(
            ImportItem(
                body=it.body,
                choices=it.choices,
                correct_answer=it.correct_answer,
                difficulty=int(it.difficulty),
                question_hash=_compute_question_hash(topic_id, it),
            )
        )
    return rows


# ----------------------------- Core processor -----------------------------


@dataclass
class ProcessResult:
    created: int
    duplicates: int
    artifact_s3_key: str | None


async def _process_job(db: AsyncSession, job: LLMJob) -> ProcessResult:
    """Process a single job from 'running' to 'succeeded' or raise to be handled."""
    assert job.topic_slug, "job.topic_slug required"
    slug = slugify(job.topic_slug)
    t0 = time.monotonic()

    # Use the topic_name from job if available, otherwise fallback to topic_slug
    display_name = job.topic_name or job.topic_slug
    
    # Ensure topic exists (idempotent)
    topic = await _ensure_topic_for_slug(db, slug=slug, display_name=display_name)

    # Commit the "running" status & topic creation before external call
    await db.commit()

    # External call (LLM) with retries - pass actual topic information
    # Use job params for description if available, otherwise use topic from DB
    topic_description = job.params.get("topic_hint_description") or topic.description
    payload = await _call_llm_generate(
        topic_slug=slug, 
        n=20, 
        topic_name=job.topic_name or topic.name, 
        topic_description=topic_description
    )

    # Validate schema
    artifact = TopicQuestionsArtifact.model_validate(payload)

    # LLM schema embeds topic metadata under `artifact.topic.slug`.
    # Older code expected `artifact.topic_slug`; be tolerant and handle
    # mismatches by logging and continuing. We will import the returned
    # questions into the requested `slug` (the topic ensured above).
    returned_slug = None
    try:
        returned_slug = getattr(artifact.topic, "slug", None)
    except Exception:
        returned_slug = None

    if returned_slug and returned_slug != slug:
        log.warning("artifact_topic_mismatch", extra={"requested": slug, "returned": returned_slug})

    # Prepare import
    items = _items_to_import(topic_id=topic.id, items=artifact.items)

    # Upsert questions
    result = await bulk_upsert_questions(db, topic_id=topic.id, items=items)
    created = int(result["created_count"])
    duplicates = int(result["duplicate_count"])

    # Publish topic if we created any items
    if created > 0:
        await db.execute(sa.update(Topic).where(Topic.id == topic.id).values(is_published=True))

    # Remove pending_topics entry if present
    await db.execute(sa.delete(PendingTopic).where(PendingTopic.topic_slug == slug))

    # Best-effort S3 upload
    raw = json.dumps(artifact.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    bucket = os.getenv("S3_BUCKET") or None
    s3_key = f"topics/{slug}/batch-{int(time.time())}.json"
    artifact_uri = _maybe_upload_s3(bucket=bucket, key=s3_key, data=raw)

    # Finalize job
    await db.execute(
        sa.update(LLMJob)
        .where(LLMJob.id == job.id)
        .values(status="succeeded", created_count=created, artifact_s3_key=artifact_uri)
    )
    await db.execute(
        pg_insert(Event).values(
            event_type="LLM_JOB_SUCCEEDED",
            payload={"job_id": str(job.id), "topic_slug": slug, "created": created, "duplicates": duplicates, "artifact": artifact_uri},
        )
    )

    await db.commit()

    log.info(
        "llm_job_succeeded",
        extra={"job_id": str(job.id), "topic_slug": slug, "created": created, "duplicates": duplicates, "artifact": artifact_uri, "duration_ms": int((time.monotonic() - t0) * 1000)},
    )

    return ProcessResult(created=created, duplicates=duplicates, artifact_s3_key=artifact_uri)


async def _fail_job(db: AsyncSession, job_id: UUID, *, error: str) -> None:
    # Check retry count and requeue if under limit
    job = (await db.execute(select(LLMJob).where(LLMJob.id == job_id))).scalar_one_or_none()
    if job:
        retry_count = getattr(job, 'retry_count', 0) or 0
        if retry_count < 3:  # Max 3 retries
            # Requeue for retry
            await db.execute(
                sa.update(LLMJob)
                .where(LLMJob.id == job_id)
                .values(status="queued", retry_count=retry_count + 1, error=None)
            )
            await db.execute(pg_insert(Event).values(
                event_type="LLM_JOB_REQUEUED", 
                payload={"job_id": str(job_id), "retry_count": retry_count + 1, "error": error}
            ))
            log.warning("llm_job_requeued", extra={"job_id": str(job_id), "retry_count": retry_count + 1, "error": error})
        else:
            # Final failure after retries
            await db.execute(sa.update(LLMJob).where(LLMJob.id == job_id).values(status="failed", error=error))
            await db.execute(pg_insert(Event).values(event_type="LLM_JOB_FAILED", payload={"job_id": str(job_id), "error": error}))
            log.error("llm_job_failed_final", extra={"job_id": str(job_id), "error": error})
    await db.commit()


# ----------------------------- Entry point -----------------------------


async def run_once(max_jobs: int = 1) -> int:
    """Process up to `max_jobs` queued jobs. Returns number of jobs processed (success or fail)."""
    settings = get_settings()
    async_engine = create_async_engine(settings.DATABASE_URL, future=True, echo=False)
    SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(bind=async_engine, expire_on_commit=False, class_=AsyncSession)
    processed = 0
    for _ in range(max_jobs):
        async with SessionLocal() as db:
            # Claim a job in a transaction
            async with db.begin():
                job = await _claim_oldest_job(db)
                if not job:
                    return processed
                job_id = job.id
                job_type = job.job_type
                topic_slug = job.topic_slug

            try:
                async with SessionLocal() as db2:
                    # refresh job state for processing context
                    j = (await db2.execute(select(LLMJob).where(LLMJob.id == job_id))).scalar_one()
                    
                    # Dispatch by job type
                    if job_type == "learning_material_generation":
                        from app.features.llm.handler_learning_materials import handle_learning_material_job
                        await handle_learning_material_job(db2, j)
                    elif job_type in ("study_buddy_reply", "study_session_summary"):
                        from app.features.llm.handler_study_reply import handle_study_reply_job
                        await handle_study_reply_job(db2, j)
                    else:
                        # Default: legacy topic generation
                        await _process_job(db2, j)
                    
                processed += 1
            except Exception as e:
                # mark failed
                async with SessionLocal() as db3:
                    await _fail_job(db3, job_id, error=str(e))
                processed += 1
                continue
    return processed


async def _amain() -> None:
    settings = get_settings()
    max_jobs = int(os.getenv("WORKER_BATCH_SIZE", "1"))
    cnt = await run_once(max_jobs=max_jobs)
    log.info("worker_run_complete", extra={"processed": cnt})


def main() -> None:
    """Synchronous entrypoint for systemd timer."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
