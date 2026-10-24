"""Add created_at and updated_at to sessions

Revision ID: 0005_add_sessions_timestamps
Revises: 0004_add_mastery_reached
Create Date: 2025-10-03
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0005_add_sessions_timestamps"
down_revision = "0004_add_mastery_reached"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns nullable with server defaults so inserts continue to work
    op.add_column(
        "sessions",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )

    # Backfill created_at from started_at when available, else now()
    op.execute("UPDATE sessions SET created_at = COALESCE(started_at, now()) WHERE created_at IS NULL")

    # Ensure updated_at is populated
    op.execute("UPDATE sessions SET updated_at = now() WHERE updated_at IS NULL")

    # Make columns NOT NULL to match ORM
    op.alter_column("sessions", "created_at", nullable=False)
    op.alter_column("sessions", "updated_at", nullable=False)


def downgrade() -> None:
    op.drop_column("sessions", "updated_at")
    op.drop_column("sessions", "created_at")
