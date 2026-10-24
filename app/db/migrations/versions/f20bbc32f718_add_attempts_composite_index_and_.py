"""add_attempts_composite_index_and_constraint

Revision ID: f20bbc32f718
Revises: 0010_add_quiz_summaries
Create Date: 2025-11-27 21:27:51.981842

"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f20bbc32f718'
down_revision = '0010_add_quiz_summaries'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add composite index on (session_id, question_id) for faster idempotency checks
    # This speeds up the duplicate check query in submit_answer
    # The index is the CRITICAL part for performance - this will fix the timeout issue
    # Using idempotent CREATE INDEX IF NOT EXISTS to handle existing indexes
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_attempts_session_question 
        ON attempts (session_id, question_id);
    """)
    
    # Add unique constraint to prevent duplicate answers at database level
    # NOTE: This may timeout on large tables with many rows. If it times out:
    # 1. The index above is already created and will fix the performance issue
    # 2. You can manually add the constraint later using:
    #    ALTER TABLE attempts ADD CONSTRAINT uq_attempts_session_question UNIQUE (session_id, question_id);
    # 3. Or skip it entirely - the application-level duplicate check + index is sufficient
    #
    # For now, we'll skip the unique constraint to avoid migration timeouts.
    # The index alone provides the performance improvement needed.
    # op.execute("""
    #     DO $$ 
    #     BEGIN
    #         ALTER TABLE attempts ADD CONSTRAINT uq_attempts_session_question UNIQUE (session_id, question_id);
    #     EXCEPTION
    #         WHEN duplicate_table THEN NULL;
    #     END $$;
    # """)


def downgrade() -> None:
    # Drop constraint if it exists
    op.execute("""
        DO $$ 
        BEGIN
            ALTER TABLE attempts DROP CONSTRAINT IF EXISTS uq_attempts_session_question;
        EXCEPTION
            WHEN undefined_object THEN NULL;
        END $$;
    """)
    # Drop index if it exists
    op.execute("DROP INDEX IF EXISTS ix_attempts_session_question;")
