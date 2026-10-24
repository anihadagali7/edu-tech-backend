# Database

Postgres, hosted on Neon (see [decisions.md](decisions.md)). The schema is defined in two places:

- **Models:** `app/db/models.py` (core) and `app/db/models_study.py` (Study Buddy). The app reads and writes through these.
- **Migrations:** `app/db/migrations/versions/` (Alembic). These build the real tables. Current head: `0012_link_quiz_to_uid`.

Conventions: every primary key is a UUID made by `gen_random_uuid()`, which comes from the `pgcrypto` extension that migration 0001 turns on. Every timestamp is `timestamptz` and defaults to `now()`. Flexible data (answer choices, explanations, job params, event payloads) is stored as `JSONB`.

## 1. Core tables (quiz platform)

```mermaid
erDiagram
    app_users ||--o{ sessions : "takes"
    app_users ||--o{ quiz_summaries : "has"
    app_users ||--o{ llm_jobs : "requested_by"
    app_users ||--o{ pending_topics : "requested_by"
    app_users ||--o{ events : "user_id"
    topics ||--o{ questions : "has"
    topics ||--o{ sessions : "quizzed in"
    topics ||--o{ quiz_summaries : ""
    sessions ||--o{ attempts : "has"
    sessions ||--o| quiz_summaries : "summarized by"
    sessions ||--o{ events : "session_id"
    questions ||--o{ attempts : "answered in"

    app_users {
        uuid id PK
        text clerk_user_id UK "Clerk 'sub' claim"
        text full_name
        text avatar_url
        bool profile_complete
        int age
        text highest_education_level
        json subjects_of_interest
        timestamptz created_at
        timestamptz updated_at
    }
    topics {
        uuid id PK
        text name UK
        text slug UK "kebab-case, used in URLs and jobs"
        text description
        bool is_published "only published topics are listed"
        bool is_deleted "soft delete"
        timestamptz created_at
        timestamptz updated_at
    }
    questions {
        uuid id PK
        uuid topic_id FK "on delete cascade"
        smallint difficulty "1 (easy) to 5 (hard)"
        text body
        jsonb choices "{A,B,C,D}"
        text correct_answer "A|B|C|D"
        jsonb explanations "{correct, distractors{A..D}}"
        text source "e.g. llm"
        text question_hash UK "dedupe across jobs"
        timestamptz created_at
    }
    sessions {
        uuid id PK
        uuid user_id FK
        uuid topic_id FK
        text session_uid UK "public id used in URLs"
        text quiz_uid UK
        text status "active|paused|completed"
        smallint current_difficulty "starts at 3"
        int streak_correct
        int streak_wrong
        bool mastery_reached
        timestamptz started_at
        timestamptz ended_at
    }
    attempts {
        uuid id PK
        uuid session_id FK "cascade"
        uuid question_id FK "cascade"
        text selected_answer
        bool is_correct
        int elapsed_ms
        timestamptz created_at
    }
    quiz_summaries {
        uuid id PK
        uuid session_id FK,UK
        uuid user_id FK
        uuid topic_id FK
        int total_attempts
        int correct_answers
        numeric accuracy "0.0000 to 1.0000"
        smallint final_difficulty
        bool mastery_reached
        timestamptz ended_at
    }
    llm_jobs {
        uuid id PK
        text job_type "generate_topic | learning_material_generation | study_buddy_reply"
        text status "queued|running|succeeded|failed"
        smallint priority
        text topic_slug
        text topic_name
        jsonb params
        uuid requested_by FK
        text error
        int retry_count
        int created_count "questions inserted"
        text artifact_s3_key "unused after revival (no S3)"
        timestamptz created_at
        timestamptz updated_at
    }
    pending_topics {
        uuid id PK
        text topic_slug UK
        text display_name
        text status "queued|rejected"
        uuid requested_by FK
        timestamptz created_at
    }
    events {
        uuid id PK
        uuid session_id FK
        uuid user_id FK
        text event_type "e.g. QUIZ_START, ATTEMPT_RECORDED, LLM_JOB_SUCCEEDED"
        jsonb payload
        timestamptz created_at
    }
```

What each table is for:

| Table | Purpose | Written by |
|---|---|---|
| `app_users` | One row per Clerk user. **Roles are not stored here.** They come from the JWT on every request. | `clerk_auth_dependency` (upsert on each call), `/profile` |
| `topics` | The topic catalog. A topic shows up for learners only when `is_published` is true and `is_deleted` is false. | Worker (creates and publishes), admin endpoints |
| `questions` | Multiple-choice questions, five difficulty levels. `question_hash` stops the same question from being inserted twice. | Worker, `POST /admin/questions/import` |
| `sessions` | One quiz run. Holds the live adaptive state: difficulty, streaks, mastery. | Quiz service |
| `attempts` | One row per answered question. A unique `(session_id, question_id)` means a question is never repeated within a session. | Quiz service |
| `quiz_summaries` | Totals saved when a quiz ends, so history pages need no recount. | Quiz end/summary |
| `llm_jobs` | The job queue. The worker claims rows with `FOR UPDATE SKIP LOCKED`. | `/llm/admin/*`, `/learning-content/*` |
| `pending_topics` | Learner topic requests waiting for an admin. Deleted when the job succeeds. | `/request-topic` |
| `events` | Audit log for jobs and answers. Feeds the admin events page. | Everywhere |

## 2. Study Buddy and learning-material tables

These are used only when `ENABLE_STUDY_BUDDY=1` or `ENABLE_LEARNING_MATERIALS=1`.

```mermaid
erDiagram
    topics ||--o{ learning_materials : "about"
    llm_jobs ||--o| learning_materials : "generated by"
    app_users ||--o{ learning_materials : "requested_by"
    learning_materials ||--o{ learning_sections : "has"
    app_users ||--o{ study_sessions : "user_id"
    topics ||--o{ study_sessions : ""
    learning_materials ||--o{ study_sessions : "material_id"
    sessions ||--o{ study_sessions : "linked by session_uid"
    study_sessions ||--o{ study_messages : "has"
    study_sessions ||--o{ study_question_history : "has"
    study_sessions ||--o{ study_analytics : "has"
    questions ||--o{ study_question_history : ""

    learning_materials {
        uuid id PK
        uuid topic_id FK
        text title
        text summary
        text content_markdown
        enum status "draft|published|archived"
        text artifact_uri
        uuid requested_by FK
        uuid job_id FK
    }
    learning_sections {
        uuid id PK
        uuid material_id FK
        text title
        text content_markdown
        int position
    }
    study_sessions {
        uuid id PK
        uuid user_id FK
        text user_clerk_id "used for ownership checks"
        uuid topic_id FK
        uuid material_id FK
        text linked_quiz_session_id FK "references sessions.session_uid"
        enum mode "reading|quiz|review|planning"
        enum status "active|completed|archived|abandoned"
        smallint hint_level
        smallint hint_budget "default 3"
        smallint frustration_score
        jsonb context_snapshot
        timestamptz last_message_at
    }
    study_messages {
        uuid id PK
        uuid session_id FK
        enum role "user|assistant|system|tool"
        enum message_type "chat|hint|summary|plan|system"
        text content
        smallint hint_level
        int tokens
        jsonb metadata
    }
    study_question_history {
        uuid id PK
        uuid session_id FK
        uuid question_id FK
        text user_answer
        enum outcome "correct|incorrect|hint|skipped|unknown"
        jsonb metadata
    }
    study_analytics {
        uuid id PK
        uuid session_id FK
        text event_type "TUTOR_REPLY, SESSION_SUMMARY, ..."
        jsonb payload "GIN index"
    }
```

`study_messages` is the chat history. Today the tutor reads only the last 5 rows, as plain text. The [chatbot guide](learning/04-chatbot.md) changes that so they are sent as real conversation turns.

`study_sessions.linked_quiz_session_id` holds the quiz's public `session_uid` (text), not `sessions.id`. Migration `0012_link_quiz_to_uid` made that change, so the UI can pass the same id it already has in the URL.

## 3. Migrations on a fresh database

The old Supabase database is gone, so every table starts empty and nothing needs to be preserved.

- **Heads are merged.** `0011_merge_heads` joins the two `0010` branches, and the chain ends at one head, `0012_link_quiz_to_uid`. `alembic heads` should print one line.
- **Several migrations are written to be re-runnable** (`IF NOT EXISTS` / `DO $$` blocks in `0010_add_quiz_summaries`, `f20bbc32f718` and `0012`). They were patched to survive a database that was partly migrated by hand. On a clean Neon database they should simply run. Test that once on a Neon branch before production.
- **Leftover columns.** The chain still creates a few columns the models no longer use: `topics.topic_uid`, `app_users.active_org_id`, `app_users.active_org_slug`, and `sessions.updated_at`. They do no harm.
- **If the chain fails on a clean database,** the simplest fix is to replace all the migration files with one fresh starting migration generated from the models (`alembic revision --autogenerate -m baseline`, plus `CREATE EXTENSION pgcrypto`). With no data to keep, this is safe.

Useful commands:

```bash
alembic heads          # exactly one line
alembic upgrade head   # build or upgrade the schema
alembic current        # what the database is on
alembic revision --autogenerate -m "describe change"   # after editing models
```

## 4. Size and load

Assumed load: a hobby app with tens of users. The largest table will be `questions`, at about 20 rows per topic per job. Neon's free 0.5 GB holds millions of question rows, so storage is not a concern for a long time. The connection pool is 5 (`app/db/base.py`), and the worker opens its own engine per run (revival step 2e). Both fit inside Neon's free connection limits.
