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
    # Create quiz_summaries table
    op.create_table(
        "quiz_summaries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", UUID(as_uuid=True), sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
        sa.Column("total_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("correct_answers", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("accuracy", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0.0")),  # 0.0000 to 1.0000
        sa.Column("final_difficulty", sa.SmallInteger(), nullable=False, server_default=sa.text("3")),
        sa.Column("mastery_reached", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    
    # Create indexes for efficient querying
    op.create_index("ix_quiz_summaries_user_id", "quiz_summaries", ["user_id"])
    op.create_index("ix_quiz_summaries_topic_id", "quiz_summaries", ["topic_id"])
    op.create_index("ix_quiz_summaries_ended_at", "quiz_summaries", ["ended_at"])
    op.create_index("ix_quiz_summaries_accuracy", "quiz_summaries", ["accuracy"])
    op.create_index("ix_quiz_summaries_user_topic_date", "quiz_summaries", ["user_id", "topic_id", "ended_at"])
    
    # Add index on sessions for future pause/resume queries (status column already exists)
    op.create_index("ix_sessions_user_status", "sessions", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_sessions_user_status", table_name="sessions")
    op.drop_table("quiz_summaries")

