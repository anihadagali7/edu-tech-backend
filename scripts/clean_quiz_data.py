#!/usr/bin/env python3
"""Clean all quiz-related data from the database.

This script deletes:
- All quiz sessions and attempts
- All questions
- All topics
- All LLM jobs
- All pending topic requests
- Related events

PRESERVES:
- Database schema (no DROP TABLE)
- User accounts and authentication data
- Application configuration

SAFETY:
- Uses transactions (rollback on error)
- Prompts for confirmation
- Shows counts before deletion
- Logs all operations

Usage:
    python scripts/clean_quiz_data.py
    python scripts/clean_quiz_data.py --force  # Skip confirmation
"""

import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import argparse
import logging
from typing import Dict

from sqlalchemy import text, select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import get_settings
from app.db.models import (
    Attempt,
    Session as QuizSession,
    Question,
    Topic,
    LLMJob,
    PendingTopic,
    Event,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


async def get_table_counts(db: AsyncSession) -> Dict[str, int]:
    """Get current row counts for all tables we'll clean."""
    counts = {}
    
    tables = [
        ("attempts", Attempt),
        ("sessions", QuizSession),
        ("questions", Question),
        ("topics", Topic),
        ("llm_jobs", LLMJob),
        ("pending_topics", PendingTopic),
        ("events", Event),
    ]
    
    for table_name, model in tables:
        result = await db.execute(select(func.count()).select_from(model))
        counts[table_name] = result.scalar() or 0
    
    return counts


async def clean_all_quiz_data(db: AsyncSession, dry_run: bool = False) -> Dict[str, int]:
    """Delete all quiz-related data in the correct order.
    
    Order matters due to foreign key constraints:
    1. attempts (references sessions, questions)
    2. sessions (references topics, users)
    3. questions (references topics)
    4. topics (standalone)
    5. llm_jobs (standalone)
    6. pending_topics (standalone)
    7. events (references sessions, users - but nullable)
    
    Args:
        db: Database session
        dry_run: If True, rollback instead of commit
        
    Returns:
        Dictionary with deleted counts per table
    """
    deleted = {}
    
    try:
        log.info("Starting deletion process...")
        
        # 1. Delete all attempts first (child of sessions and questions)
        log.info("Deleting attempts...")
        result = await db.execute(delete(Attempt))
        deleted['attempts'] = result.rowcount or 0
        log.info(f"  Deleted {deleted['attempts']} attempts")
        
        # 2. Delete all quiz sessions (child of topics and users, but we keep users)
        log.info("Deleting quiz sessions...")
        result = await db.execute(delete(QuizSession))
        deleted['sessions'] = result.rowcount or 0
        log.info(f"  Deleted {deleted['sessions']} sessions")
        
        # 3. Delete all questions (child of topics)
        log.info("Deleting questions...")
        result = await db.execute(delete(Question))
        deleted['questions'] = result.rowcount or 0
        log.info(f"  Deleted {deleted['questions']} questions")
        
        # 4. Delete all topics (now safe, no children left)
        log.info("Deleting topics...")
        result = await db.execute(delete(Topic))
        deleted['topics'] = result.rowcount or 0
        log.info(f"  Deleted {deleted['topics']} topics")
        
        # 5. Delete all LLM jobs
        log.info("Deleting LLM jobs...")
        result = await db.execute(delete(LLMJob))
        deleted['llm_jobs'] = result.rowcount or 0
        log.info(f"  Deleted {deleted['llm_jobs']} LLM jobs")
        
        # 6. Delete all pending topics
        log.info("Deleting pending topics...")
        result = await db.execute(delete(PendingTopic))
        deleted['pending_topics'] = result.rowcount or 0
        log.info(f"  Deleted {deleted['pending_topics']} pending topics")
        
        # 7. Delete quiz-related events (optional - keeps audit trail clean)
        log.info("Deleting quiz-related events...")
        # Delete events that reference deleted sessions or are quiz-related
        event_types = [
            'QUIZ_START',
            'ATTEMPT_RECORDED',
            'LLM_JOB_CREATED',
            'LLM_JOB_RUNNING',
            'LLM_JOB_SUCCEEDED',
            'LLM_JOB_FAILED',
            'LLM_JOB_REQUEUED',
        ]
        result = await db.execute(
            delete(Event).where(Event.event_type.in_(event_types))
        )
        deleted['events'] = result.rowcount or 0
        log.info(f"  Deleted {deleted['events']} events")
        
        if dry_run:
            log.warning("DRY RUN MODE - Rolling back all changes")
            await db.rollback()
            return deleted
        
        # Commit the transaction
        log.info("Committing transaction...")
        await db.commit()
        log.info("✅ All deletions committed successfully")
        
        return deleted
        
    except Exception as e:
        log.error(f"❌ Error during deletion: {e}", exc_info=True)
        await db.rollback()
        raise


async def vacuum_and_analyze(db: AsyncSession):
    """Run VACUUM and ANALYZE to reclaim space and update statistics."""
    log.info("Running VACUUM ANALYZE to reclaim space...")
    
    # Note: VACUUM cannot run inside a transaction block
    # We need to use autocommit mode
    await db.commit()  # Ensure no open transaction
    
    try:
        # Get raw connection for VACUUM
        connection = await db.connection()
        await connection.exec_driver_sql("VACUUM ANALYZE")
        log.info("✅ VACUUM ANALYZE completed")
    except Exception as e:
        log.warning(f"⚠️  VACUUM ANALYZE failed (this is optional): {e}")


async def main():
    parser = argparse.ArgumentParser(
        description="Clean all quiz-related data from database"
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompt'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without actually deleting'
    )
    parser.add_argument(
        '--no-vacuum',
        action='store_true',
        help='Skip VACUUM ANALYZE step'
    )
    
    args = parser.parse_args()
    
    # Get settings and create engine
    settings = get_settings()
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        future=True,
    )
    
    SessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    try:
        # Show current counts
        log.info("=" * 60)
        log.info("DATABASE CLEANUP SCRIPT")
        log.info("=" * 60)
        
        async with SessionLocal() as db:
            log.info("\nCurrent database contents:")
            counts_before = await get_table_counts(db)
            
            for table, count in counts_before.items():
                log.info(f"  {table:20s}: {count:6d} rows")
            
            total_rows = sum(counts_before.values())
            log.info(f"\n  {'TOTAL':20s}: {total_rows:6d} rows")
        
        # Confirmation prompt
        if not args.force and not args.dry_run:
            log.warning("\n⚠️  WARNING: This will DELETE all quiz data!")
            log.warning("   - All quiz sessions and attempts")
            log.warning("   - All questions and topics")
            log.warning("   - All LLM jobs and pending requests")
            log.warning("   - Related events")
            log.warning("\n   USER DATA WILL BE PRESERVED")
            
            response = input("\nAre you sure you want to continue? Type 'yes' to confirm: ")
            if response.lower() != 'yes':
                log.info("❌ Aborted by user")
                return 1
        
        if args.dry_run:
            log.info("\n🔍 DRY RUN MODE - No data will be deleted")
        
        # Execute deletion
        log.info("\n" + "=" * 60)
        log.info("STARTING DELETION")
        log.info("=" * 60 + "\n")
        
        async with SessionLocal() as db:
            deleted = await clean_all_quiz_data(db, dry_run=args.dry_run)
        
        # Show results
        log.info("\n" + "=" * 60)
        log.info("DELETION SUMMARY")
        log.info("=" * 60)
        
        for table, count in deleted.items():
            log.info(f"  {table:20s}: {count:6d} rows deleted")
        
        total_deleted = sum(deleted.values())
        log.info(f"\n  {'TOTAL':20s}: {total_deleted:6d} rows deleted")
        
        if args.dry_run:
            log.info("\n🔍 DRY RUN COMPLETE - No changes were made")
            return 0
        
        # Vacuum and analyze (optional)
        if not args.no_vacuum:
            log.info("\n" + "=" * 60)
            async with SessionLocal() as db:
                await vacuum_and_analyze(db)
        
        # Verify deletion
        log.info("\n" + "=" * 60)
        log.info("VERIFICATION")
        log.info("=" * 60 + "\n")
        
        async with SessionLocal() as db:
            counts_after = await get_table_counts(db)
            
            log.info("Remaining rows:")
            for table, count in counts_after.items():
                log.info(f"  {table:20s}: {count:6d} rows")
            
            total_remaining = sum(counts_after.values())
            log.info(f"\n  {'TOTAL':20s}: {total_remaining:6d} rows")
        
        log.info("\n" + "=" * 60)
        log.info("✅ DATABASE CLEANUP COMPLETED SUCCESSFULLY")
        log.info("=" * 60)
        
        return 0
        
    except Exception as e:
        log.error(f"\n❌ Fatal error: {e}", exc_info=True)
        return 1
    
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
