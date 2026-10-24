"""Add profile fields to app_users: profile_complete, age, highest_education_level, subjects_of_interest

Revision ID: 0008_add_profile_fields
Revises: 549eef2d08a5
Create Date: 2025-10-12
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "0008_add_profile_fields"
down_revision = "549eef2d08a5"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add profile completion flag
    op.add_column(
        "app_users",
        sa.Column("profile_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    
    # Add age field
    op.add_column(
        "app_users",
        sa.Column("age", sa.Integer(), nullable=True)
    )
    
    # Add highest education level field
    op.add_column(
        "app_users",
        sa.Column("highest_education_level", sa.Text(), nullable=True)
    )
    
    # Add subjects of interest as JSONB array
    op.add_column(
        "app_users",
        sa.Column("subjects_of_interest", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb"))
    )

def downgrade() -> None:
    op.drop_column("app_users", "subjects_of_interest")
    op.drop_column("app_users", "highest_education_level")
    op.drop_column("app_users", "age")
    op.drop_column("app_users", "profile_complete")

