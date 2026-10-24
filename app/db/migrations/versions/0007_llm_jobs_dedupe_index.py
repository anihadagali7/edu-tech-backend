"""Add partial unique index to llm_jobs to deduplicate queued/running jobs per topic

Revision ID: 0007_llm_jobs_dedupe_index
Revises: 0006_align_models_schema
Create Date: 2025-10-03
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0007_llm_jobs_dedupe_index"
down_revision = "0006_align_models_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create a partial unique index to prevent multiple queued/running generate_topic jobs for the same topic
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_jobs_topic_generate_active ON llm_jobs (job_type, topic_slug) WHERE status IN ('queued','running')")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_llm_jobs_topic_generate_active")
