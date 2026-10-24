"""Add organization support to app_users

Revision ID: 0008_add_organization_support
Revises: 549eef2d08a5
Create Date: 2025-01-11 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0008_add_organization_support'
down_revision = '549eef2d08a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add organization-related columns to app_users table."""
    # Add organization-related fields to app_users
    op.add_column('app_users', sa.Column('active_org_id', sa.Text(), nullable=True))
    op.add_column('app_users', sa.Column('active_org_role', sa.Text(), nullable=True))
    op.add_column('app_users', sa.Column('active_org_slug', sa.Text(), nullable=True))
    
    # Add index for active_org_id for better query performance
    op.create_index('ix_app_users_active_org_id', 'app_users', ['active_org_id'])


def downgrade() -> None:
    """Remove organization-related columns from app_users table."""
    # Drop index first
    op.drop_index('ix_app_users_active_org_id', table_name='app_users')
    
    # Drop columns
    op.drop_column('app_users', 'active_org_slug')
    op.drop_column('app_users', 'active_org_role')
    op.drop_column('app_users', 'active_org_id')