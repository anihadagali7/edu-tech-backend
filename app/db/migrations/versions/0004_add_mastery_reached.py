"""Add mastery_reached to sessions

Revision ID: 0004_add_mastery_reached
Revises: 0003_add_topic_uid
Create Date: 2025-10-03
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0004_add_mastery_reached"
down_revision = "0003_add_topic_uid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add column as nullable with server default so concurrent inserts keep working
    op.add_column(
        "sessions",
        sa.Column("mastery_reached", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )

    # Backfill existing rows to false where NULL
    op.execute("UPDATE sessions SET mastery_reached = false WHERE mastery_reached IS NULL")

    # Make NOT NULL to match ORM
    op.alter_column("sessions", "mastery_reached", nullable=False)


def downgrade() -> None:
    op.drop_column("sessions", "mastery_reached")
