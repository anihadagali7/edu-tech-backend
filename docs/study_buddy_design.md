# AI Study Buddy System Design

## 1. Objectives
- Introduce an AI-powered study companion that delivers context-aware guidance across the learning journey.
- Generate, store, and serve high-quality learning materials alongside existing quizzes without breaking current APIs.
- Reuse existing services (LLM worker, topics/questions, SSE) while keeping new dependencies minimal and modular.
- Capture analytics for future personalization and model training, respecting privacy and system performance.

## 2. Key Capabilities
1. **Learning Material Generation**: Produce detailed topic explainers, examples, and practice guidance; store in Postgres (primary) with optional S3 offload for rich media.
2. **Contextual Study Buddy Chat**: Provide adaptive assistance everywhere—content pages, quizzes, dashboards—behaving differently based on learner activity.
3. **Question History Tracking**: Persist per-user question outcomes to avoid repeats after successful attempts and power adaptive difficulty.
4. **Analytics & Telemetry**: Log study sessions, hints, content usage, and outcomes for downstream analysis.

## 3. Architecture Overview
```
+-----------------------+        +--------------------+        +--------------------+
|       Frontend        | <----> |   FastAPI Backend   | <----> |   Postgres (Supabase) |
| (web / mobile clients)|        |                    |        |   + Optional S3     |
+-----------+-----------+        +---------+----------+        +--------------------+
            |                                |                              |
            |                                |                              |
            |                                v                              v
            |                        +---------------+             +--------------------+
            |                        | Study Buddy    |             | LLM Provider       |
            |                        | Orchestrator   |             | (OpenAI)           |
            |                        +---------------+             +--------------------+
            |                                |
            v                                v
   +--------------------+             +---------------+
   | Event/SSE Channel  |<----------- | Worker Runner |
   +--------------------+             +---------------+
                                  (Processes LLM jobs,
                                  generates content,
                                  logs analytics)
```

### Components
- **Study Buddy Router (`app/features/study_buddy`)**: REST + SSE endpoints for session management, messages, hints, analytics submissions.
- **Learning Content Service (`app/features/learning_content`)**: Handles generation jobs, storage, retrieval, and metadata.
- **Conversation Orchestrator**: Builds prompts using learner context, routes to LLM, enforces role-specific behavior (reader vs. quiz-taker).
- **Worker Extensions**: Add job types for `LEARNING_MATERIAL_GENERATION`, `STUDY_BUDDY_REPLY`, `SESSION_SUMMARY`, reusing existing async runner.
- **Analytics Collector**: Centralizes logging of interactions into `study_analytics` tables and existing events system.

## 4. Data Model Additions
(All tables in Postgres/Supabase; consider JSONB for flexible payloads.)

### 4.1 Learning Content
- `learning_materials`
  - `id UUID PK`
  - `topic_id` (FK `topics.id`)
  - `title`
  - `summary`
  - `body_markdown` (rich text; store canonical version)
  - `reading_time_minutes`
  - `resources` JSONB (links, media)
  - `metadata` JSONB (difficulty, prerequisites)
  - `storage_backend` enum (`postgres`, `s3`)
  - `s3_key` nullable (when large assets stored externally)
  - `llm_job_id` nullable (generation trace)
  - `created_at`, `updated_at`

- `learning_sections` (optional normalization for modular content)
  - `id`, `material_id`, `heading`, `body_markdown`, `order_index`

### 4.2 Study Sessions & Messages
- `study_sessions`
  - `id UUID PK`
  - `user_id` (FK `users.id`)
  - `topic_id` nullable
  - `current_mode` enum (`reading`, `quiz`, `review`, `planning`)
  - `status` enum (`active`, `completed`, `abandoned`)
  - `goals` JSONB (targets, deadlines)
  - `context_snapshot` JSONB (content IDs, quiz info)
  - `started_at`, `updated_at`, `ended_at`

- `study_messages`
  - `id UUID PK`
  - `session_id` (FK `study_sessions.id`)
  - `sender` enum (`user`, `assistant`, `system`)
  - `message_type` enum (`chat`, `hint`, `summary`, `plan`)
  - `body` TEXT (render-ready markdown)
  - `payload` JSONB (structured hints, question IDs, citations)
  - `related_question_id` nullable (FK `questions.id`)
  - `created_at`

- `study_session_context`
  - `session_id`
  - `key`
  - `value` JSONB (cached values for quick lookups, e.g., last question details)

### 4.3 Question History & Analytics
- `question_history`
  - `id`
  - `user_id`
  - `question_id`
  - `last_attempt_at`
  - `attempts` INT
  - `first_correct_at` nullable
  - `last_result` enum (`correct`, `incorrect`, `skipped`)
  - `session_id` nullable

- `study_analytics`
  - `id`
  - `user_id`
  - `event_type` (`CONTENT_VIEW`, `HINT_REQUEST`, `QUIZ_COMPLETED`, etc.)
  - `session_id` nullable
  - `topic_id`, `question_id` nullable
  - `metadata` JSONB (latency, prompt tokens, feedback)
  - `created_at`

- Extend `events` table with new `event_type`s for study buddy interactions to reuse existing SSE pipeline.

## 5. Learning Material Generation Pipeline
1. **Trigger**: Admin or automated cadence enqueues `LEARNING_MATERIAL_GENERATION` job per topic (via new endpoint or background scheduler).
2. **Worker Handler**: Fetch topic metadata, existing questions, and desired outline (from curated template). Compose prompt instructing LLM to produce structured markdown sections, key takeaways, practice problems.
3. **Validation**: Parse LLM output using Pydantic schema (e.g., `LearningMaterialArtifact`). Validate sections, word counts, inclusion of exercises. Auto-repair minor issues (similar to question schema handling).
4. **Storage**: Save markdown to `learning_materials.body_markdown`; optionally generate plain-text summary, compute reading time. If assets (images, diagrams) requested, store base64 or upload to S3 (via worker) and store `s3_key`.
5. **Serving**: API exposes `GET /learning-materials/{topic_slug}` returning structured content; caches via HTTP caching or CDN if using S3.

## 6. Study Buddy Behavior Logic

### 6.1 Mode Detection
- Mode derived from user context:
  - **Reading**: active content page with `learning_material_id` reference.
  - **Quiz**: active quiz session/attempt; obtains `question_id`, `attempt_id`.
  - **Review/Planning**: dashboard or summary screens.
- Frontend sends `mode` + relevant resource IDs with each message; backend cross-validates (e.g., confirm quiz attempt exists and is active).
- Orchestrator adjusts prompts + allowed tools per mode.

### 6.2 Prompt Templates
- **Reading Mode Prompt**: Encourage detailed explanations, analogies, references to current section; allow follow-up questions, citations from stored material.
- **Quiz Mode Prompt**: Provide hints only; enforce guardrail that correct answers must not be revealed. Use partial credit strategies (Socratic questioning). Include system message: "Do not give away answers; respond with hints only." If the user demands the answer, refuse politely.
- **Context Retrieval**: Orchestrator fetches `learning_materials`, `study_messages` (limited recent history), `question_history`, and current question details. Maintains summary state to stay within token limits.

### 6.3 Automatic Context Linking
- When message arrives with `mode=quiz` and `question_id` absent, orchestrator attempts to infer question from session context (last question served, or active attempt). If disambiguation fails, prompt assistant to clarify.
- For reading mode, highlight sections by referencing `learning_sections` metadata, enabling targeted clarifications ("refer to section 3.2").

### 6.4 Response Delivery
- Primary responses returned via REST; optionally stream using SSE for typing indicator or incremental hints.
- Responses stored in `study_messages` with metadata (token usage, classification scores) for analytics.

## 7. APIs

### 7.1 Learning Content
- `POST /admin/learning-materials/generate` (feature-flagged) → enqueue generation job(s) for topics.
- `GET /learning-materials` → list available materials with summaries.
- `GET /learning-materials/{topic}` → fetch material + sections.
- Optional `PATCH` endpoints for manual edits (admin only).

### 7.2 Study Buddy Sessions
- `POST /study-buddy/sessions` → start session; accepts `mode`, `topic_id`, `goal`, `learning_material_id`.
- `GET /study-buddy/sessions` → list user sessions (pagination).
- `GET /study-buddy/sessions/{id}` → session metadata + last N messages, current mode.
- `POST /study-buddy/sessions/{id}/messages` → send message; body includes `mode`, `context` (e.g., `learning_material_id`, `question_id`, `quiz_attempt_id`). Response includes assistant message, hints, optional SSE stream.
- `POST /study-buddy/sessions/{id}/quiz-response` → reuse existing quiz evaluation but link result to session and update question history.
- `POST /study-buddy/sessions/{id}/analytics` → capture client-side events (time-on-page, hint interaction) if needed.

### 7.3 Question History
- `GET /users/{id}/question-history` (admin) → inspect performance.
- Updates happen automatically through quiz attempt processing and study buddy hint flow.

### 7.4 Analytics
- Extend SSE feed or add `GET /admin/study-analytics` for reporting.
- Optional export job to S3 for offline processing.

-## 8. Worker & Background Jobs
- Extend `app/features/llm/worker.py` to support new job types:
  - `LEARNING_MATERIAL_GENERATION`
  - `STUDY_BUDDY_REPLY` (for long-form responses requiring asynchronous computation)
  - `STUDY_SESSION_SUMMARY`
- Each job stores structured artifacts validated with Pydantic models, similar to question generation.
- Add rate-limiting and batching controls to avoid overwhelming LLM provider.

## 9. Analytics & Telemetry
- Instrument endpoints with structured logs (user ID hashed/obfuscated if needed). Capture:
  - Material views (duration, sections accessed).
  - Chat interactions (modes, number of hints requested, satisfaction feedback if available).
  - Quiz performance over time, hint usage correlation.
- Store aggregated metrics in `study_analytics`; schedule nightly exports to S3 for long-term retention/training.
- Add Prometheus/Grafana dashboards (optional) or reuse existing monitoring stack.

## 10. Security & Privacy

## 11. Frontend Considerations (for coordination)

## 12. Incremental Delivery Plan
1. **Foundations**
   - Add migrations for new tables.
   - Create feature flags/config entries.
   - Scaffold repositories/services for sessions, messages, materials, analytics.

2. **Learning Materials MVP**
   - Implement generation job + admin trigger + public read endpoints.
   - Build validation schemas and templates.

3. **Study Buddy Chat (Reading Mode)**
   - Session creation, message exchange, context injection from learning materials.
   - Basic analytics logging.

4. **Quiz Mode Integration**
   - Link to quiz attempts, enforce hint-only responses, update question history.
   - UI adjustments for hint workflows.

5. **Question History Enforcement**
   - Update question selection logic to filter out previously mastered items.
   - Provide admin analytics/reporting.

6. **Comprehensive Analytics**
   - Expand logging, dashboards, export pipelines.

7. **Polish & Scale**
   - Session summaries, study plans, caching, optional S3 asset support, rate limiting.

## 13. Risks & Mitigations
- **Token Cost Spike**: Use session summaries, context truncation, adjustable section depth. Monitor via analytics.
- **Content Quality Variance**: Keep human-in-the-loop review for initial materials; add automated quality checks (readability, coverage).
- **Mode Misclassification**: Ensure frontend passes explicit mode & IDs; backend verifies via active session/attempt records.
- **Data Growth**: Schedule archival tasks for old sessions/material versions; leverage S3 for large assets.
- **Latency**: Use asynchronous jobs for heavy operations; stream responses; consider caching frequently accessed materials.

## 14. Compatibility with Existing System
- All new routes isolated under `/study-buddy` and `/learning-materials`; no breaking changes to existing quiz endpoints.
- Worker changes additive: job router identifies new job types without altering existing behavior.
- SSE expanded with new event types but retains backward compatibility for existing channels.
- Configuration defaults keep feature off until migrations and UI updates deployed.

## 15. Tooling & Dependencies
- Continue using OpenAI client; optional additional embedding model only if required for semantic search (defer unless necessary).
- Prefer Postgres JSONB for content; integrate S3 via boto3 only when storing large assets (lazy import to avoid dependency overhead).
- Optional Redis/WebSocket server deferred until real-time needs exceed SSE capability.

## 16. Next Steps for Engineering
1. Review & approve schema changes; plan migrations.
2. Define LLM prompts/templates for learning materials and contextual buddy responses.
3. Implement repositories/services + API scaffolding with feature flag.
4. Coordinate with frontend to incorporate mode signals and new UI components.
5. Establish analytics metrics & logging strategy.
6. Pilot on limited set of topics; gather feedback before broad rollout.
