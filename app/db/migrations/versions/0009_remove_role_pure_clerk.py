"""Remove role column for Pure Clerk implementation

Revision ID: 0009_remove_role_pure_clerk
Revises: 0008_add_organization_support
Create Date: 2025-01-11 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0009_remove_role_pure_clerk'
down_revision = '0008_add_organization_support'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove role column and active_org_role - all roles from Clerk."""
    # Remove role-related columns that are now managed by Clerk
    op.drop_column('app_users', 'role')
    op.drop_column('app_users', 'active_org_role')


def downgrade() -> None:
    """Restore role columns if needed."""
    # Restore columns (data will be lost)
    op.add_column('app_users', sa.Column('role', sa.Text(), nullable=True))
    op.add_column('app_users', sa.Column('active_org_role', sa.Text(), nullable=True))