"""Alter linked_quiz_session_id from UUID to TEXT to reference sessions.session_uid.

Revision ID: 0012_link_quiz_to_uid
Revises: 0011_merge_heads
Create Date: 2025-01-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0012_link_quiz_to_uid"
down_revision = "0011_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Change linked_quiz_session_id from UUID to TEXT and update foreign key
    to reference sessions.session_uid instead of sessions.id.
    """
    # First, drop the existing foreign key constraint if it exists
    # PostgreSQL might auto-generate a different constraint name
    op.execute("""
        DO $$ 
        DECLARE
            constraint_name TEXT;
        BEGIN
            SELECT conname INTO constraint_name
            FROM pg_constraint 
            WHERE conrelid = 'study_sessions'::regclass 
            AND conname LIKE '%linked_quiz_session_id%'
            AND contype = 'f'
            LIMIT 1;
            
            IF constraint_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE study_sessions DROP CONSTRAINT IF EXISTS %I', constraint_name);
            END IF;
        END $$;
    """)
    
    # PostgreSQL doesn't allow subqueries in USING clause, so we need to:
    # 1. Add a temporary TEXT column
    # 2. Populate it with session_uid values
    # 3. Drop the old UUID column
    # 4. Rename the temp column to the original name
    
    # Step 1: Add temporary column
    op.execute("""
        ALTER TABLE study_sessions 
        ADD COLUMN linked_quiz_session_id_new TEXT;
    """)
    
    # Step 2: Populate the new column by looking up session_uid
    op.execute("""
        UPDATE study_sessions ss
        SET linked_quiz_session_id_new = s.session_uid
        FROM sessions s
        WHERE ss.linked_quiz_session_id = s.id
          AND ss.linked_quiz_session_id IS NOT NULL;
    """)
    
    # Step 3: Drop the old column
    op.execute("""
        ALTER TABLE study_sessions 
        DROP COLUMN linked_quiz_session_id;
    """)
    
    # Step 4: Rename the new column to the original name
    op.execute("""
        ALTER TABLE study_sessions 
        RENAME COLUMN linked_quiz_session_id_new TO linked_quiz_session_id;
    """)
    
    # Step 5: Add the new foreign key constraint referencing sessions.session_uid
    op.create_foreign_key(
        "study_sessions_linked_quiz_session_id_fkey",
        "study_sessions",
        "sessions",
        ["linked_quiz_session_id"],
        ["session_uid"],
        ondelete="SET NULL"
    )


def downgrade() -> None:
    """
    Revert linked_quiz_session_id back to UUID referencing sessions.id.
    """
    # Drop the foreign key constraint on session_uid if it exists
    op.execute("""
        DO $$ 
        DECLARE
            constraint_name TEXT;
        BEGIN
            SELECT conname INTO constraint_name
            FROM pg_constraint 
            WHERE conrelid = 'study_sessions'::regclass 
            AND conname LIKE '%linked_quiz_session_id%'
            AND contype = 'f'
            LIMIT 1;
            
            IF constraint_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE study_sessions DROP CONSTRAINT IF EXISTS %I', constraint_name);
            END IF;
        END $$;
    """)
    
    # Same approach for downgrade: use temporary column
    # Step 1: Add temporary UUID column
    op.execute("""
        ALTER TABLE study_sessions 
        ADD COLUMN linked_quiz_session_id_new UUID;
    """)
    
    # Step 2: Populate the new column by looking up session id from session_uid
    op.execute("""
        UPDATE study_sessions ss
        SET linked_quiz_session_id_new = s.id
        FROM sessions s
        WHERE ss.linked_quiz_session_id = s.session_uid
          AND ss.linked_quiz_session_id IS NOT NULL;
    """)
    
    # Step 3: Drop the old TEXT column
    op.execute("""
        ALTER TABLE study_sessions 
        DROP COLUMN linked_quiz_session_id;
    """)
    
    # Step 4: Rename the new column to the original name
    op.execute("""
        ALTER TABLE study_sessions 
        RENAME COLUMN linked_quiz_session_id_new TO linked_quiz_session_id;
    """)
    
    # Step 5: Add back the foreign key constraint referencing sessions.id
    op.create_foreign_key(
        "study_sessions_linked_quiz_session_id_fkey",
        "study_sessions",
        "sessions",
        ["linked_quiz_session_id"],
        ["id"],
        ondelete="SET NULL"
    )
