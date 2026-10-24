"""Align DB schema with ORM models: attempts & questions

Revision ID: 0006_align_models_schema
Revises: 0005_add_sessions_timestamps
Create Date: 2025-10-03
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0006_align_models_schema"
down_revision = "0005_add_sessions_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- attempts: rename columns to match ORM ---
    # chosen_choice_id -> selected_answer
    op.alter_column("attempts", "chosen_choice_id", new_column_name="selected_answer")

    # response_time_ms -> elapsed_ms
    op.alter_column("attempts", "response_time_ms", new_column_name="elapsed_ms")

    # answered_at -> created_at
    op.alter_column("attempts", "answered_at", new_column_name="created_at")

    # Make selected_answer nullable to match ORM
    op.alter_column("attempts", "selected_answer", nullable=True)

    # Ensure created_at present and not null with default now()
    # If created_at exists via rename, set server default and fill NULLs
    op.alter_column(
        "attempts",
        "created_at",
        server_default=sa.text("now()"),
        nullable=True,
    )
    op.execute("UPDATE attempts SET created_at = now() WHERE created_at IS NULL")
    op.alter_column("attempts", "created_at", nullable=False)

    # --- questions: make explanations NOT NULL with default '{}' ---
    op.alter_column(
        "questions",
        "explanations",
        existing_type=sa.dialects.postgresql.JSONB,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )

    # Make source nullable to match ORM (was NOT NULL with server default 'llm')
    op.alter_column(
        "questions",
        "source",
        existing_type=sa.Text(),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    # Revert questions changes
    op.alter_column(
        "questions",
        "source",
        existing_type=sa.Text(),
        nullable=False,
        server_default=sa.text("'llm'"),
    )
    op.alter_column(
        "questions",
        "explanations",
        existing_type=sa.dialects.postgresql.JSONB,
        nullable=True,
        server_default=None,
    )

    # Revert attempts column renames
    op.alter_column("attempts", "created_at", new_column_name="answered_at")
    op.alter_column("attempts", "elapsed_ms", new_column_name="response_time_ms")
    op.alter_column("attempts", "selected_answer", new_column_name="chosen_choice_id")
