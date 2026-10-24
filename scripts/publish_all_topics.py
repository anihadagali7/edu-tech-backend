#!/usr/bin/env python3
"""Publish all unpublished topics.

This script will:
- Find topics where is_published is False
- Set is_published = True for each topic
- Emit a TOPIC_PUBLISHED event for audit/logging

Usage:
    python scripts/publish_all_topics.py       # interactive confirmation
    python scripts/publish_all_topics.py --force   # no prompt
    python scripts/publish_all_topics.py --dry-run # show what would be done
    python scripts/publish_all_topics.py --slug science  # publish only topic with slug 'science'

Be careful: this mutates production data. Always run with --dry-run first if unsure.
"""

import asyncio
import sys
from pathlib import Path
import argparse
import logging

# Ensure project root is on path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import get_settings
from app.db.models import Topic, Event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scripts.publish_all_topics")


async def publish_topics(slug: str | None = None, dry_run: bool = False) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    published_count = 0
    try:
        async with SessionLocal() as session:
            # Build query for unpublished topics
            if slug:
                stmt = select(Topic).where(Topic.slug == slug)
            else:
                stmt = select(Topic).where(Topic.is_published == False)

            result = await session.execute(stmt)
            rows = result.scalars().all()

            if not rows:
                log.info("No matching topics found to publish")
                return 0

            log.info(f"Found {len(rows)} topic(s) to publish")
            for t in rows:
                log.info(f"  - {t.slug} (id={t.id}) currently is_published={t.is_published}")

            if dry_run:
                log.info("Dry run mode - no changes will be made")
                return len(rows)

            # Confirm and apply updates
            for t in rows:
                await session.execute(
                    update(Topic).where(Topic.id == t.id).values(is_published=True)
                )
                # Emit event
                await session.execute(
                    pg_insert(Event).values(event_type="TOPIC_PUBLISHED", payload={"topic_id": t.id, "slug": t.slug, "name": t.name, "is_published": True})
                )
                published_count += 1

            await session.commit()
            log.info(f"Published {published_count} topics")
            return published_count

    finally:
        await engine.dispose()


async def main():
    parser = argparse.ArgumentParser(description="Publish unpublished topics")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be published without making changes")
    parser.add_argument("--slug", type=str, help="Only publish the topic with this slug")

    args = parser.parse_args()

    if not args.force and not args.dry_run:
        confirm = input("This will publish topics (set is_published=True). Type 'yes' to continue: ")
        if confirm.lower() != "yes":
            log.info("Aborted by user")
            return 1

    count = await publish_topics(slug=args.slug, dry_run=args.dry_run)
    if args.dry_run:
        log.info(f"DRY RUN: {count} topics would be published")
    else:
        log.info(f"Done: {count} topics published")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
