# Current System Design (November 2025)

This document captures the **implemented** architecture of the `edu-tech-backend` project based on the codebase as of November 2025. Every section references actual modules, schemas, and flows found in the repository to provide an accurate snapshot of what exists today.

---

## 1. High-Level Overview

- **Service type:** FastAPI backend (`app/main.py`) exposing JSON APIs, Clerk-backed authentication, and Server-Sent Events (SSE) for real-time quiz feedback.
- **Primary domains:**
  - Topic catalog management (public listing + admin curation).
  - Adaptive quiz sessions with per-answer explanations and summaries.
  - LLM-driven content generation pipeline (topic/question creation).
  - Admin reporting + basic user profile management.
- **Data store:** PostgreSQL/Supabase accessed via async SQLAlchemy (`app/db/base.py`).
- **Background processing:** OpenAI-powered worker that drains `llm_jobs` queue to generate questions (`app/features/llm/worker.py`, legacy runner in `worker/runner.py`).
- **Observability:** Structured JSON logging, request correlation, and an `events` audit table powering SSE updates and analytics.

---

## 2. Runtime Components

### 2.1 API application
- `app/main.py` constructs the FastAPI app, wires CORS, JSON logging middleware (`RequestIDMiddleware`), exception envelopes, and mounts all routers from `app/api/routes.py`.
- Response shape standardized via `app/auth/schemas.Envelope`.
- `/health` endpoint (no auth) confirms liveness.

### 2.2 Authentication & Authorization
- Clerk JWT validation implemented in `app/auth/middleware.py`:
  - Fetches JWKS with caching (`_get_jwks`).
  - Verifies issuer/audience, extracts Clerk `sub`, optionally role metadata.
  - Upserts `app_users` row (`_upsert_app_user`) and attaches `request.state.user` containing UUID, profile flags, and role.
- Dependencies:
  - `clerk_auth_dependency` -> requires valid JWT.
  - `require_role`, `require_admin_or_org_admin`, `require_org_role` enforce RBAC for admin routes.

### 2.3 Database Layer
- `app/db/base.py` creates async engine & session factory (`SessionLocal`) with connect-arg sanitation for asyncpg.
- Models in `app/db/models.py` cover `AppUser`, `Topic`, `Question`, `Session`, `Attempt`, `LLMJob`, `PendingTopic`, and `Event`.
- Repository helpers in `app/db/repositories.py` encapsulate CRUD, counts, exports, and queue upserts.

### 2.4 Event Streaming (SSE)
- `app/features/quizzes/sse.py` exposes SSE endpoints under `/sse/quiz/*`.
- `QuizSessionManager` tracks subscribers, publishes events, and delegates business logic to `AdaptiveService` for consistency with REST endpoints.
- Heartbeat payloads (30s) prevent idle timeouts; events include `session_started`, `question`, `answer`, `needs_refill`, `summary`.

### 2.5 Background Workers
- **Primary async worker:** `app/features/llm/worker.py` (used by `run_worker.py` and systemd) pulls queued `LLMJob`s, calls OpenAI, validates output (`app/features/llm/schema`), upserts questions, marks topics published, stores artifacts (optional S3), and handles retries via `_fail_job`.
- **Legacy runner class:** `worker/runner.py` + `worker/db.py` implement similar workflow using a `LLMWorkerRunner` class; currently leveraged by `app/features/llm/auto_worker.AutoWorker`, which reinitializes the runner when `OPENAI_MODEL` changes and processes a single job on demand.
- Jobs are triggered automatically via `trigger_worker_async` background task when admin endpoints create new jobs.

---

## 3. Data Model Snapshot

| Table | Purpose | Key Fields / Notes |
|-------|---------|--------------------|
| `app_users` | Minimal user profile keyed by Clerk `sub`. | `profile_complete`, `age`, `highest_education_level`, `subjects_of_interest` persisted after profile update (`app/features/profile.py`). |
| `topics` | Catalog of learning topics. | `topic_uid` (ULID), `slug` unique, `is_published`, `is_deleted`. Questions relationship. |
| `questions` | Multiple-choice questions with explanations. | JSONB `choices`, JSONB `explanations` (per-option reasons), `difficulty` 1-5, dedup by `question_hash` computed with `app/utils/qhash.py`. |
| `sessions` | Adaptive quiz sessions. | `session_uid` (public), `quiz_uid`, difficulty tracking (`current_difficulty`, streaks, `mastery_reached`). |
| `attempts` | One row per answered question. | Links session/question, stores `selected_answer`, correctness, `elapsed_ms`. |
| `llm_jobs` | Queue for generation work. | `status` (`queued`, `running`, `succeeded`, `failed`), `params` JSON (batch size, language, etc.), `retry_count`, `artifact_s3_key`. |
| `pending_topics` | User topic requests awaiting admin approval. | Unique `topic_slug`, `status` (`queued`, `approved`, `rejected`). |
| `events` | Append-only audit/event log. | `event_type` (e.g., `QUIZ_START`, `ATTEMPT_RECORDED`, `LLM_JOB_SUCCEEDED`), JSON `payload`, optional `session_id`/`user_id`. |

---

## 4. Core Feature Implementations

### 4.1 Topic Management (`app/features/topics.py`)
- **Public endpoints:**
  - `GET /topics` lists published topics, optionally fuzzy search `q`, and injects live question counts via `count_questions_by_topic`.
  - `GET /topics/{id}` returns a single published topic.
  - `GET /search` runs published search; when no match, emits confirmation payload to request new topic via `slugify` guardrails.
- **Topic request flow:**
  - `POST /request-topic` validates slug length, inserts `PendingTopic`, emits `TOPIC_REQUESTED` event.
- **Admin operations (auth via Clerk + admin role):**
  - `POST /admin/topics` creates curated topic (emits `TOPIC_CREATED`).
  - `PATCH /admin/topics/{id}` updates details, toggles publication (emits `TOPIC_PUBLISHED`/`TOPIC_UNPUBLISHED`).
  - `DELETE /admin/topics/{id}` soft deletes by default (`is_deleted = true`).
  - `POST /admin/questions/import` bulk upserts question payloads.

### 4.2 Adaptive Quiz Lifecycle
- **Service logic (`app/features/quizzes/service.py`):**
  - `AdaptiveService.start_quiz` ensures topic existence (by name -> placeholder + queued job via `_ensure_topic_by_name`), inserts session row (`SessionView`), and picks first question using `_select_next_question` with `FOR UPDATE SKIP LOCKED` to avoid duplicates.
  - `submit_answer` enforces ownership/role, prevents duplicates, computes streak logic to adjust difficulty, writes `Attempt`, updates `Session`, emits `ATTEMPT_RECORDED`, and selects next question. Returns `needs_refill` when no suitable question remains.
  - `summarize_session` aggregates accuracy by difficulty and produces summary metrics.
- **REST endpoints (`app/features/quizzes/router.py`):**
  - `POST /quizzes/start` -> returns session metadata + optional first question, publishes SSE `started` event.
  - `POST /quizzes/{session_uid}/answer` -> records answer, publishes SSE `answer` & `question` events.
  - `GET /quizzes/{session_uid}/summary` -> fetches summary, pushes SSE `summary`.
- **SSE subsystem (`app/features/quizzes/sse.py`):**
  - `GET /sse/quiz/start` -> starts session, streams events.
  - `POST /sse/quiz/{session_uid}/answer` -> returns correctness plus `explanation` block containing `correct_explanation`, `selected_explanation/why_wrong`, and `all_explanations` from `questions.explanations` JSON.
  - `GET /sse/quiz/{session_uid}/summary` -> extends summary with analytics (question history, strengths/weaknesses, recommendations).
  - Manager ensures heartbeat events, and `publish_session_event` helper reused by REST layer.

### 4.3 LLM Content Pipeline
- **Job management (`app/features/llm/jobs.py`):**
  - Admin endpoints create or approve topics creating queued jobs with parameters, promoting pending requests to `approved`, and invoking `trigger_worker_async`.
  - `GET /llm/admin/jobs` lists jobs with filters; `GET /llm/admin/pending-requests` surfaces user-submitted topics.
  - `POST /llm/admin/pending-requests/{id}/reject` updates status; `DELETE /llm/admin/jobs/{id}` (if implemented) uses repository functions.
- **Auto worker trigger (`app/features/llm/auto_worker.py`):**
  - Maintains singleton `AutoWorker` with `LLMWorkerRunner` instance; reinitializes when `OPENAI_MODEL` changes.
- **Worker execution (`app/features/llm/worker.py`):**
  - `_claim_oldest_job` marks job `running` and emits `LLM_JOB_RUNNING`.
  - `_call_llm_generate` (provider-agnostic) currently supports OpenAI via `app.features.llm.provider_openai`.
  - Responses validated by `TopicQuestionsArtifact` (`app/features/llm/schema.py`), gracefully logging slug mismatches, and converting to `ImportItem` list.
  - Inserts questions via `bulk_upsert_questions`, publishes topics when new items were created, deletes `pending_topics`, uploads artifacts to S3 if configured, updates job status, and emits `LLM_JOB_SUCCEEDED`.
  - `_fail_job` handles retries (max 3) before marking `failed` and emitting `LLM_JOB_FAILED`/`LLM_JOB_REQUEUED`.
- **Legacy runner (`worker/runner.py`):**
  - Provides `LLMWorkerRunner` class returning `schemas.artifact.JobResult`, using `worker/db.DatabaseManager` for DB operations; includes repair attempts for malformed JSON and event emission.
  - Still used indirectly by auto worker; ensures compatibility with CLI tests.
- **Prompts (`prompts/llm_topic_questions.py` and `app/features/llm/prompt.py`):**
  - Rich system prompts enforce difficulty distribution, explanation structure, and output schema.
  - Utility `create_repair_prompt` supports retrying malformed JSON.

### 4.4 Admin Reporting (`app/features/admin/reporting.py`)
- Endpoints (all require admin):
  - `GET /admin/users` -> pagination + filters, uses `admin_list_users` repo helper.
  - `GET /admin/events` -> filters by type/user/session/time, via `admin_list_events`.
  - `GET /admin/events/count`, `GET /admin/questions/count` -> summary metrics (latter uses `count_total_questions`).
  - `GET /admin/export.{fmt}` -> JSON/CSV exports for users, topics (via `admin_snapshot_topics`), or events.
- Responses include metadata for front-end table consumption.

### 4.5 Profile Management (`app/features/profile.py`)
- `PUT /profile` updates `app_users` demographics (age, education, subjects) and marks `profile_complete`.
- `GET /profile` returns persisted profile state.
- Validation ensures subjects list lengths, enumerated education level, and subject normalization to lowercase.

### 4.6 Pending Topic & Search Integration
- `app/features/topics.search` surfaces matching published topics. If none:
  - Guard slug length >= 3 before prompting for confirmation.
  - Checks existing `PendingTopic` to avoid duplicates.
- `request_topic_creation` writes `PendingTopic`, commits, emits event and returns message used by UI.
- `AdaptiveService._ensure_topic_by_name` automatically seeds `PendingTopic` and a queued `LLMJob` when learners start quizzes for unknown topics.

### 4.7 Development/Test Utilities
- `app/features/dev_routes.py` exposes `/dev/topics-noauth` for unauthenticated topic listing (development only, flagged for removal in production).
- Scripts under `scripts/`:
  - `clean_quiz_data.py` (safe deletion/dry-run for quiz tables).
  - `retry_failed_job.py` resets failed LLM jobs to `queued`.
  - `publish_all_topics.py` publishes unpublished topics and emits `TOPIC_PUBLISHED` events.
  - Additional helpers (`inspect_jobs.py`, `list_recent_questions.py`, etc.) assist operations.

---

## 5. Eventing, Analytics & Logging

- `app/utils/logging.setup_logging` configures JSON logging with request IDs; every request gets `X-Request-ID` header (`RequestIDMiddleware`).
- `events` table acts as the unified audit and analytics stream:
  - Populated across features (`QUIZ_START`, `ATTEMPT_RECORDED`, `TOPIC_*`, `LLM_JOB_*`).
  - SSE and admin analytics read from this table to power UI badges and monitoring.
- Additional analytics surfaces:
  - `app/features/quizzes/sse.get_session_summary` constructs detailed performance insights (accuracy by difficulty, strengths/weaknesses, improvement areas, recommendations).
  - Admin reporting endpoints supply aggregated counts for dashboards.

---

## 6. Configuration & Deployment Considerations

- `app/config.Settings` defines environment-driven configuration with `.env` support for local dev. Key settings:
  - `DATABASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, Clerk keys, optional `AWS_REGION`/`S3_BUCKET`, SSE heartbeat interval.
  - Defaults include `CORS_ORIGINS` `http://localhost:3000`/`5173`, `APP_ENV=dev`.
- Worker entrypoints:
  - `python run_worker.py` executes `app/features/llm/worker.main()` (async run-once, `WORKER_BATCH_SIZE` env controls loop).
  - Legacy CLI: `python -m worker.runner --loop` exists for compatibility (depends on `worker` package).
- Deployment artifacts under `deploy/` (systemd service/timer, nginx config) orchestrate periodic worker execution and API hosting.

---

## 7. External Dependencies

- **Clerk** for auth + role management (JWT-based).
- **OpenAI** via LangChain for question generation (`langchain`, `langchain-openai`).
- **SQLAlchemy** (async) and `asyncpg` for DB access.
- **Pydantic v2** for schema validation (extensively in `schemas/artifact.py`, `app/features/llm/schema.py`).
- Optional: `python-dotenv` (dev), `boto3` when S3 upload configured.

---

## 8. Current Limitations & Observed Behavior

- Two worker implementations exist (`app/features/llm/worker` and `worker/runner`). Auto-worker uses the legacy runner; manual CLI uses the app-integrated worker. Keeping both in sync requires care.
- SSE quiz implementation wraps REST service methods for consistency but still maintains independent logic for analytics aggregation—changes must be mirrored across both code paths.
- `topics.request_topic_creation` stores requests but relies on admin jobs to fulfil them; no automatic feedback loop yet.
- No explicit rate limiting or feature flag toggles—exposed endpoints rely solely on Clerk roles.
- Dev router (`/dev/...`) is present; ensure it is disabled in production.

---

## 9. Summary of Implemented Endpoints

| Area | Path(s) | Notes |
|------|---------|-------|
| Health | `GET /health` | No auth. |
| Auth Profile | `GET /me`, `/profile` (GET/PUT) | Requires Clerk auth. |
| Topics | `/topics`, `/topics/{id}`, `/search`, `/request-topic` | Public (auth required). |
| Admin Topics | `/admin/topics` (POST/PATCH/DELETE), `/admin/questions/import` | Admin role required. |
| Quizzes (REST) | `/quizzes/start`, `/quizzes/{session}/answer`, `/quizzes/{session}/summary` | Adaptive flow. |
| Quizzes (SSE) | `/sse/quiz/start`, `/sse/quiz/{session}/answer`, `/sse/quiz/{session}/summary` | Streaming events + analytics. |
| LLM Jobs | `/llm/admin/*` (pending requests, approve/create/reject, list jobs) | Admin only, auto-runs worker. |
| Admin Reporting | `/admin/users`, `/admin/events`, `/admin/events/count`, `/admin/questions/count`, `/admin/export.{fmt}` | CSV/JSON exports + pagination. |
| Dev Utilities | `/dev/topics-noauth` | Auth bypass for local testing. |

---

## 10. Operational Tooling & Scripts

- `scripts/clean_quiz_data.py` — transactionally wipes quiz/topic/job tables with dry-run/force flags.
- `scripts/retry_failed_job.py` — requeues failed jobs (single or all).
- `scripts/publish_all_topics.py` — flips `is_published=True` for unpublished topics and emits `TOPIC_PUBLISHED` events.
- Additional scripts (e.g., `scripts/inspect_jobs.py`, `scripts/list_recent_questions.py`) provide ad-hoc diagnostics.

---

## 11. Next Steps (For Context)

While outside the scope of the current system, recently drafted documents (e.g., `docs/study_buddy_design.md`) propose future extensions. The details above reflect only the **implemented** system verified by inspecting the codebase, ensuring the design document remains an accurate representation of the deployed functionality today.
