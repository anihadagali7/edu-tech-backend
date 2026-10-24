"""Database operations for LLM worker.

Provides async database helpers for job processing, topic management, 
question deduplication, and event logging.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

import sqlalchemy as sa
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, Event, LLMJob, Question, Topic
from app.utils.qhash import compute_question_hash
from schemas.artifact import QuestionArtifact, QuestionUpsertResult

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Async database manager for LLM worker operations."""
    
    def __init__(self, database_url: str):
        """Initialize database manager.
        
        Args:
            database_url: SQLAlchemy database URL (may include sslmode=require)
        """
        self.database_url = database_url
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            future=True,
            # Handle SSL mode transparently
            connect_args=self._get_connect_args(database_url),
        )
        self.SessionLocal = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    
    def _get_connect_args(self, database_url: str) -> Dict[str, Any]:
        """Extract SSL connection args from database URL."""
        connect_args = {}
        if "sslmode=require" in database_url.lower():
            connect_args["server_settings"] = {"jit": "off"}
        return connect_args
    
    @asynccontextmanager
    async def get_session(self) -> AsyncIterator[AsyncSession]:
        """Get async database session."""
        session = self.SessionLocal()
        try:
            yield session
        finally:
            await session.close()
    
    async def claim_next_job(self) -> Optional[LLMJob]:
        """Atomically claim the next queued job.
        
        Uses FOR UPDATE SKIP LOCKED to prevent race conditions.
        Sets status from 'queued' to 'running'.
        
        Returns:
            Claimed job or None if no jobs available
        """
        async with self.get_session() as session:
            try:
                # Find and lock the oldest queued job
                stmt = (
                    sa.select(LLMJob)
                    .where(LLMJob.status == "queued")
                    .order_by(LLMJob.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                
                result = await session.execute(stmt)
                job = result.scalar_one_or_none()
                
                if job is None:
                    logger.debug("No queued jobs available")
                    return None
                
                # Update status to running
                job.status = "running"
                job.updated_at = sa.func.now()
                
                await session.commit()
                
                logger.info(f"Claimed job {job.id} for topic '{job.topic_slug}'")
                return job
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to claim job: {e}")
                raise
    
    async def ensure_topic(
        self, 
        slug: str, 
        name: str, 
        description: str | None = None
    ) -> uuid.UUID:
        """Ensure topic exists, creating or updating as needed.
        
        Args:
            slug: Topic slug (unique identifier)
            name: Display name for topic
            description: Optional topic description
            
        Returns:
            Topic UUID
        """
        async with self.get_session() as session:
            try:
                # Try to find existing topic
                stmt = sa.select(Topic).where(Topic.slug == slug)
                result = await session.execute(stmt)
                existing_topic = result.scalar_one_or_none()
                
                if existing_topic:
                    # Update existing topic if needed
                    updated = False
                    if existing_topic.name != name:
                        existing_topic.name = name
                        updated = True
                    if description and existing_topic.description != description:
                        existing_topic.description = description
                        updated = True
                    
                    if updated:
                        existing_topic.updated_at = sa.func.now()
                        await session.commit()
                        logger.info(f"Updated existing topic {existing_topic.id} ({slug})")
                    
                    return existing_topic.id
                
                # Create new topic
                topic = Topic(
                    topic_uid=f"topic_{slug}",  # Generate appropriate topic_uid
                    slug=slug,
                    name=name,
                    description=description,
                    is_published=False,  # Default to unpublished
                )
                
                session.add(topic)
                await session.commit()
                await session.refresh(topic)
                
                logger.info(f"Created new topic {topic.id} ({slug})")
                return topic.id
                
            except IntegrityError as e:
                await session.rollback()
                # Handle race condition - topic might have been created concurrently
                logger.warning(f"Topic creation race condition for slug '{slug}': {e}")
                
                # Retry lookup
                stmt = sa.select(Topic).where(Topic.slug == slug)
                result = await session.execute(stmt)
                topic = result.scalar_one()
                return topic.id
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to ensure topic '{slug}': {e}")
                raise
    
    def compute_question_hash(
        self,
        topic_id: uuid.UUID,
        body: str,
        correct_answer: str,
    ) -> str:
        """Delegate to shared compute_question_hash utility for consistency."""
        return compute_question_hash(topic_id, body, correct_answer)
    
    async def upsert_questions(
        self, 
        topic_id: uuid.UUID, 
        questions: list[QuestionArtifact]
    ) -> QuestionUpsertResult:
        """Upsert questions with deduplication.
        
        Uses ON CONFLICT (question_hash) DO NOTHING for deduplication.
        
        Args:
            topic_id: Topic UUID to associate questions with
            questions: List of question artifacts to insert
            
        Returns:
            Result with counts of created/duplicate questions
        """
        if not questions:
            return QuestionUpsertResult(
                created_count=0,
                duplicate_count=0,
                total_processed=0
            )
        
        async with self.get_session() as session:
            try:
                # Prepare question records
                question_records = []
                for q in questions:
                    question_hash = self.compute_question_hash(
                        topic_id, q.body, q.correct_answer
                    )
                    
                    # Prepare explanations JSON
                    explanations = {
                        "correct": q.explanations.correct,
                        "distractors": q.explanations.distractors
                    }
                    
                    # Add sources to explanations if present
                    if q.sources:
                        explanations["sources"] = q.sources
                    
                    question_records.append({
                        "id": uuid.uuid4(),
                        "topic_id": topic_id,
                        "difficulty": q.difficulty,
                        "body": q.body.strip(),
                        "choices": q.choices,
                        "correct_answer": q.correct_answer,
                        "question_hash": question_hash,
                        "explanations": explanations,
                        "source": ", ".join(q.sources) if q.sources else None,
                    })
                
                # Batch upsert with conflict resolution
                stmt = insert(Question).values(question_records)
                stmt = stmt.on_conflict_do_nothing(index_elements=["question_hash"])
                
                result = await session.execute(stmt)
                created_count = result.rowcount or 0
                
                await session.commit()
                
                duplicate_count = len(questions) - created_count
                
                logger.info(
                    f"Upserted {len(questions)} questions for topic {topic_id}: "
                    f"{created_count} created, {duplicate_count} duplicates"
                )
                
                return QuestionUpsertResult(
                    created_count=created_count,
                    duplicate_count=duplicate_count,
                    total_processed=len(questions)
                )
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to upsert questions for topic {topic_id}: {e}")
                raise
    
    async def mark_job_completed(
        self,
        job_id: uuid.UUID,
        status: str,
        error: str | None = None,
        created_count: int | None = None
    ) -> None:
        """Mark job as completed with final status.
        
        Args:
            job_id: Job UUID
            status: Final status ('succeeded' or 'failed')
            error: Error message if failed
            created_count: Number of questions created if succeeded
        """
        async with self.get_session() as session:
            try:
                stmt = sa.select(LLMJob).where(LLMJob.id == job_id)
                result = await session.execute(stmt)
                job = result.scalar_one()
                
                job.status = status
                job.updated_at = sa.func.now()
                
                if error:
                    job.error = error
                if created_count is not None:
                    job.created_count = created_count
                
                await session.commit()
                
                logger.info(f"Marked job {job_id} as {status}")
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to mark job {job_id} as {status}: {e}")
                raise
    
    async def emit_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Emit an application event.
        
        Args:
            event_type: Type of event (e.g., 'LLM_JOB_SUCCEEDED')
            payload: Event data
        """
        async with self.get_session() as session:
            try:
                event = Event(
                    event_type=event_type,
                    payload=payload,
                    session_id=None,  # LLM job events are not tied to quiz sessions
                    user_id=payload.get("user_id"),  # Extract from payload if available
                )
                
                session.add(event)
                await session.commit()
                
                logger.debug(f"Emitted event: {event_type}")
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to emit event {event_type}: {e}")
                # Don't raise - event emission failure shouldn't break job processing
    
    async def delete_pending_topic(self, topic_slug: str) -> None:
        """Delete pending topic entry if it exists.
        
        Args:
            topic_slug: Topic slug to remove from pending topics
        """
        async with self.get_session() as session:
            try:
                stmt = sa_text(
                    "DELETE FROM pending_topics WHERE topic_slug = :slug"
                )
                result = await session.execute(stmt, {"slug": topic_slug})
                
                if result.rowcount and result.rowcount > 0:
                    await session.commit()
                    logger.info(f"Deleted pending topic: {topic_slug}")
                else:
                    logger.debug(f"No pending topic found for: {topic_slug}")
                    
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to delete pending topic {topic_slug}: {e}")
                # Don't raise - this is cleanup, shouldn't break job processing
    
    async def close(self) -> None:
        """Close database engine."""
        if hasattr(self, "engine"):
            await self.engine.dispose()


# Global database manager instance
_db_manager: DatabaseManager | None = None


def get_db_manager(database_url: str | None = None) -> DatabaseManager:
    """Get global database manager instance.
    
    Args:
        database_url: Database URL (required on first call)
        
    Returns:
        Database manager instance
    """
    global _db_manager
    
    if _db_manager is None:
        if database_url is None:
            raise ValueError("database_url required on first call")
        _db_manager = DatabaseManager(database_url)
    
    return _db_manager


async def cleanup_db_manager() -> None:
    """Cleanup global database manager."""
    global _db_manager
    if _db_manager is not None:
        await _db_manager.close()
        _db_manager = None