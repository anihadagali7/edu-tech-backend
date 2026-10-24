"""Add study buddy and learning material tables.

Revision ID: 0010_study_buddy_models
Revises: 0009_remove_role_pure_clerk, 0008_add_profile_fields
Create Date: 2025-11-09

This is a merge migration that reconciles two branches and adds Study Buddy tables.
The upgrade function is idempotent - it can be safely run multiple times.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0010_study_buddy_models"
down_revision = ("0009_remove_role_pure_clerk", "0008_add_profile_fields")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Idempotent upgrade that creates Study Buddy tables and enums.
    Uses DO $$ ... EXCEPTION blocks to safely handle existing objects.
    """
    
    # Create all enum types (idempotent)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE learning_material_status AS ENUM ('draft', 'published', 'archived');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        
        DO $$ BEGIN
            CREATE TYPE study_session_mode AS ENUM ('reading', 'quiz', 'review', 'planning');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        
        DO $$ BEGIN
            CREATE TYPE study_session_status AS ENUM ('active', 'completed', 'archived', 'abandoned');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        
        DO $$ BEGIN
            CREATE TYPE study_message_role AS ENUM ('user', 'assistant', 'system', 'tool');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        
        DO $$ BEGIN
            CREATE TYPE study_message_type AS ENUM ('chat', 'hint', 'summary', 'plan', 'system');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        
        DO $$ BEGIN
            CREATE TYPE study_question_outcome AS ENUM ('correct', 'incorrect', 'hint', 'skipped', 'unknown');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
    """)
    
    # Create learning_materials table
    op.execute("""
        CREATE TABLE IF NOT EXISTS learning_materials (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            topic_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            summary TEXT,
            content_markdown TEXT,
            status learning_material_status NOT NULL DEFAULT 'draft'::learning_material_status,
            artifact_uri TEXT,
            requested_by UUID REFERENCES app_users(id) ON DELETE SET NULL,
            job_id UUID REFERENCES llm_jobs(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
        
        CREATE INDEX IF NOT EXISTS ix_learning_materials_topic_created 
            ON learning_materials(topic_id, created_at);
    """)
    
    # Create learning_sections table
    op.execute("""
        CREATE TABLE IF NOT EXISTS learning_sections (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            material_id UUID NOT NULL REFERENCES learning_materials(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            content_markdown TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
        
        CREATE INDEX IF NOT EXISTS ix_learning_sections_material_position 
            ON learning_sections(material_id, position);
    """)
    
    # Create study_sessions table
    op.execute("""
        CREATE TABLE IF NOT EXISTS study_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES app_users(id) ON DELETE SET NULL,
            user_clerk_id TEXT NOT NULL,
            topic_id UUID REFERENCES topics(id) ON DELETE SET NULL,
            material_id UUID REFERENCES learning_materials(id) ON DELETE SET NULL,
            linked_quiz_session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
            mode study_session_mode NOT NULL DEFAULT 'reading'::study_session_mode,
            status study_session_status NOT NULL DEFAULT 'active'::study_session_status,
            hint_level SMALLINT NOT NULL DEFAULT 0,
            hint_budget SMALLINT NOT NULL DEFAULT 3,
            frustration_score SMALLINT,
            context_snapshot JSONB,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            last_message_at TIMESTAMP WITH TIME ZONE
        );
        
        CREATE INDEX IF NOT EXISTS ix_study_sessions_user_created 
            ON study_sessions(user_clerk_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_study_sessions_user_id_created 
            ON study_sessions(user_id, created_at);
    """)
    
    # Create study_messages table
    op.execute("""
        CREATE TABLE IF NOT EXISTS study_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
            role study_message_role NOT NULL,
            message_type study_message_type NOT NULL DEFAULT 'chat'::study_message_type,
            content TEXT NOT NULL,
            hint_level SMALLINT,
            tokens INTEGER,
            metadata JSONB,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
        
        CREATE INDEX IF NOT EXISTS ix_study_messages_session_created 
            ON study_messages(session_id, created_at);
    """)
    
    # Create study_question_history table
    op.execute("""
        CREATE TABLE IF NOT EXISTS study_question_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
            question_id UUID REFERENCES questions(id) ON DELETE SET NULL,
            user_answer TEXT,
            outcome study_question_outcome,
            metadata JSONB,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
        
        CREATE INDEX IF NOT EXISTS ix_study_question_history_session_created 
            ON study_question_history(session_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_study_question_history_question_created 
            ON study_question_history(question_id, created_at);
    """)
    
    # Create study_analytics table
    op.execute("""
        CREATE TABLE IF NOT EXISTS study_analytics (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            payload JSONB,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
        
        CREATE INDEX IF NOT EXISTS ix_study_analytics_session_created 
            ON study_analytics(session_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_study_analytics_event_type 
            ON study_analytics(event_type);
        CREATE INDEX IF NOT EXISTS ix_study_analytics_payload_gin 
            ON study_analytics USING gin(payload);
    """)


def downgrade() -> None:
    """
    Downgrade removes all Study Buddy tables and enums.
    """
    # Drop tables in reverse dependency order
    op.execute("DROP TABLE IF EXISTS study_analytics CASCADE;")
    op.execute("DROP TABLE IF EXISTS study_question_history CASCADE;")
    op.execute("DROP TABLE IF EXISTS study_messages CASCADE;")
    op.execute("DROP TABLE IF EXISTS study_sessions CASCADE;")
    op.execute("DROP TABLE IF EXISTS learning_sections CASCADE;")
    op.execute("DROP TABLE IF EXISTS learning_materials CASCADE;")
    
    # Drop enum types
    op.execute("DROP TYPE IF EXISTS study_question_outcome CASCADE;")
    op.execute("DROP TYPE IF EXISTS study_message_type CASCADE;")
    op.execute("DROP TYPE IF EXISTS study_message_role CASCADE;")
    op.execute("DROP TYPE IF EXISTS study_session_status CASCADE;")
    op.execute("DROP TYPE IF EXISTS study_session_mode CASCADE;")
    op.execute("DROP TYPE IF EXISTS learning_material_status CASCADE;")
