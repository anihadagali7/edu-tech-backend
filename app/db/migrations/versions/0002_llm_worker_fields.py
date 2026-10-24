"""Add LLM worker fields and update job/question schemas

Revision ID: 0002_llm_worker_fields
Revises: 0001_clerk_base
Create Date: 2025-09-30
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "0002_llm_worker_fields"
down_revision = "0001_clerk_base"
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Add fields required for LLM worker functionality."""
    
    # Update llm_jobs table
    op.add_column("llm_jobs", sa.Column("topic_name", sa.Text(), nullable=True))
    op.add_column("llm_jobs", sa.Column("params", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    
    # Update job status default
    op.alter_column("llm_jobs", "status", server_default=sa.text("'queued'"))
    
    # Update questions table  
    #op.add_column("questions", sa.Column("explanations", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    #op.add_column("questions", sa.Column("source", sa.Text(), nullable=True))
    
    # Update events table to make session_id optional for system events
    op.alter_column("events", "session_id", nullable=True)

def downgrade() -> None:
    """Remove LLM worker fields."""
    
    # Revert events table
    op.alter_column("events", "session_id", nullable=False)
    
    # Remove questions fields
    #op.drop_column("questions", "source") 
    #op.drop_column("questions", "explanations")
    
    # Revert llm_jobs status default
    op.alter_column("llm_jobs", "status", server_default=sa.text("'pending'"))
    
    # Remove llm_jobs fields
    op.drop_column("llm_jobs", "params")
    op.drop_column("llm_jobs", "topic_name")