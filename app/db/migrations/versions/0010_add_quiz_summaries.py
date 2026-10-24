"""Add quiz_summaries table and indexes for quiz history

Revision ID: 0010_add_quiz_summaries
Revises: 0009_remove_role_pure_clerk, 0008_add_profile_fields
Create Date: 2025-01-15
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "0010_add_quiz_summaries"
down_revision = ("0009_remove_role_pure_clerk", "0008_add_profile_fields")  # Merge both branches
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create quiz_summaries table (idempotent - only create if doesn't exist)
    op.execute("""
        CREATE TABLE IF NOT EXISTS quiz_summaries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
            topic_id UUID REFERENCES topics(id) ON DELETE SET NULL,
            total_attempts INTEGER NOT NULL DEFAULT 0,
            correct_answers INTEGER NOT NULL DEFAULT 0,
            accuracy NUMERIC(5, 4) NOT NULL DEFAULT 0.0,
            final_difficulty SMALLINT NOT NULL DEFAULT 3,
            mastery_reached BOOLEAN NOT NULL DEFAULT false,
            ended_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT quiz_summaries_session_id_key UNIQUE (session_id)
        );
    """)
    
    # Create indexes for efficient querying (idempotent)
    op.execute("CREATE INDEX IF NOT EXISTS ix_quiz_summaries_user_id ON quiz_summaries(user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_quiz_summaries_topic_id ON quiz_summaries(topic_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_quiz_summaries_ended_at ON quiz_summaries(ended_at);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_quiz_summaries_accuracy ON quiz_summaries(accuracy);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_quiz_summaries_user_topic_date ON quiz_summaries(user_id, topic_id, ended_at);")
    
    # Add index on sessions for future pause/resume queries (status column already exists)
    op.execute("CREATE INDEX IF NOT EXISTS ix_sessions_user_status ON sessions(user_id, status);")


def downgrade() -> None:
    op.drop_index("ix_sessions_user_status", table_name="sessions")
    op.drop_table("quiz_summaries")

