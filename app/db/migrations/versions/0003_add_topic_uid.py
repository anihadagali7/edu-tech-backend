"""Add topic_uid to topics and backfill values

Revision ID: 0003_add_topic_uid
Revises: 0002_llm_worker_fields
Create Date: 2025-10-03
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003_add_topic_uid"
down_revision = "0002_llm_worker_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add column as nullable so we can backfill existing rows
    op.add_column("topics", sa.Column("topic_uid", sa.Text(), nullable=True))

    # Backfill: use slug as a stable, unique fallback for existing rows
    op.execute("UPDATE topics SET topic_uid = slug WHERE topic_uid IS NULL")

    # Enforce NOT NULL
    op.alter_column("topics", "topic_uid", nullable=False)

    # Create unique constraint consistent with ORM
    op.create_unique_constraint("uq_topics_topic_uid", "topics", ["topic_uid"])


def downgrade() -> None:
    # Remove unique constraint and column
    op.drop_constraint("uq_topics_topic_uid", "topics", type_="unique")
    op.drop_column("topics", "topic_uid")
