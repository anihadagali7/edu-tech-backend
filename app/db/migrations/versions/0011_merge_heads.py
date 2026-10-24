"""Merge migration: combine 0010_study_buddy_models and f20bbc32f718.

Revision ID: 0011_merge_heads
Revises: 0010_study_buddy_models, f20bbc32f718
Create Date: 2025-01-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0011_merge_heads"
down_revision = ("0010_study_buddy_models", "f20bbc32f718")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge point - both migrations have already been applied."""
    pass


def downgrade() -> None:
    """Merge point - no action needed."""
    pass
