# Architecture

This page shows the target setup after the 2026 revival: Vercel, Heroku, Neon, Clerk and Claude. Where today's code still differs from it, the page says so and links to [revival-plan.md](revival-plan.md).

## 1. The big picture

```mermaid
flowchart LR
    user([Learner / Admin<br/>browser])

    subgraph Vercel
        ui[edu-tech-ui<br/>Next.js 14]
    end

    subgraph Clerk
        clerk[Clerk<br/>sign-in, users,<br/>JWT signing keys]
    end

    subgraph Heroku["Heroku (1 web dyno)"]
        api[FastAPI app<br/>REST + SSE]
        bg[In-process job runner<br/>FastAPI BackgroundTasks]
        sched[Heroku Scheduler<br/>python run_worker.py<br/>every 10 min]
    end

    subgraph Neon
        db[(Postgres)]
    end

    claude[Claude API<br/>api.anthropic.com]

    user -->|pages| ui
    user <-->|sign in| clerk
    ui -->|"fetch + Bearer JWT<br/>(REST and SSE streams)"| api
    api -->|verify JWT with JWKS| clerk
    api <--> db
    api --> bg
    bg -->|generate questions| claude
    sched -->|drain stuck jobs| db
    sched --> claude
    api -->|Study Buddy replies| claude
```

What each part does:

| Part | Job |
|---|---|
| **UI** (Next.js) | Every page is a client component. It gets a Clerk token and calls the API with `fetch`. It has no database of its own. `src/app/api/*` holds only a health check and a mock list. |
| **Clerk** | Sign-up, sign-in and the user list. It signs a short-lived JWT (JSON Web Token: a signed piece of text that says who you are). The admin role lives in the user's Clerk `public_metadata`. |
| **FastAPI** | All business logic: topics, quizzes, profile, admin reports, Study Buddy. It checks each JWT against Clerk's public keys (JWKS), so it never needs to call Clerk per request. |
| **Job runner** | When an admin approves a topic, the API writes a row in `llm_jobs`. It then starts the worker right away as a background task in the same process. |
| **Scheduler** | A safety net. It runs the same worker every 10 minutes and picks up any job the API process dropped, for example because of a restart. |
| **Postgres** | The only store. Users, topics, questions, quiz sessions, answers, jobs, events and chat messages all live here. |
| **Claude** | Writes quiz questions (worker) and tutor replies (Study Buddy). Today the code calls OpenAI through LangChain. [revival-plan.md](revival-plan.md) step 4 swaps that for Claude. |

## 2. Inside the backend

```mermaid
flowchart TB
    main["app/main.py<br/>create_app: CORS, request IDs, error envelope"]
    routes["app/api/routes.py<br/>mounts every router"]
    auth["app/auth/middleware.py<br/>clerk_auth_dependency, require_role"]

    subgraph features["app/features"]
        topics["topics.py<br/>/topics /search /request-topic /admin/topics"]
        quiz["quizzes/router.py<br/>/quizzes/* history + REST quiz"]
        sse["quizzes/sse.py<br/>/sse/quiz/* live quiz"]
        llm["llm/jobs.py<br/>/llm/admin/* approve, create, jobs"]
        worker["llm/worker.py<br/>run_once: claim job, call LLM, insert questions"]
        provider["llm/provider_openai.py<br/>(becomes provider_claude.py)"]
        profile["profile.py<br/>/profile"]
        admin["admin/reporting.py<br/>/admin/users /admin/events"]
        sb["study_buddy/*<br/>/study-buddy/* and /sse/study-buddy/*<br/>flag: ENABLE_STUDY_BUDDY"]
        lc["learning_content/*<br/>/learning-content/*<br/>flag: ENABLE_LEARNING_MATERIALS"]
    end

    db["app/db<br/>models.py, models_study.py, repositories.py, migrations"]

    main --> routes --> features
    features --> auth
    llm -->|BackgroundTasks| worker --> provider
    features --> db
    worker --> db
```

Folder notes:

- `app/` is the live code. Start reading at `app/api/routes.py`.
- `worker/` and `run_worker.py`: `run_worker.py` calls `app/features/llm/worker.py`. The `worker/` folder is an older second worker. Only `tests/test_worker_smoke.py` uses it.
- `prompts/` holds the prompt text. The `.md` files are templates with `{{placeholders}}`.
- The `test_*.py`, `check_*.py`, `reset_migration.py` and `*_SUMMARY.md` files at the repo root are one-off debug scripts and status notes. Nothing imports them.

## 3. Request flows

### 3.1 Sign in and call the API

```mermaid
sequenceDiagram
    participant B as Browser (UI)
    participant C as Clerk
    participant A as FastAPI
    participant D as Postgres

    B->>C: sign in
    C-->>B: session + short-lived JWT
    B->>A: GET /me  (Authorization: Bearer JWT)
    A->>C: GET JWKS (cached 5 min)
    A->>A: verify signature + issuer, read sub and role
    A->>D: upsert app_users by clerk_user_id
    A-->>B: {id, clerk_user_id, role, profile fields}
```

The first API call creates the user's row. No sign-up webhook is needed.

### 3.2 Take an adaptive quiz (live stream)

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as FastAPI (one process)
    participant M as In-memory broker<br/>(QuizSessionManager)
    participant D as Postgres

    B->>A: GET /sse/quiz/start?topic_id=…  (stream stays open)
    A->>D: create sessions row (difficulty 3)
    A->>M: subscribe(session_uid)
    A-->>B: event: session_started
    A-->>B: event: question
    loop each answer
        B->>A: POST /sse/quiz/{uid}/answer  (separate request)
        A->>D: lock session row, insert attempt, update difficulty/streaks
        A->>M: publish answer_feedback, then question or quiz_completed
        M-->>B: events arrive on the open stream
    end
    A-->>B: event: heartbeat (every 10 s)
```

> **Important limit.** The broker is a Python dict in one process. The answer POST must reach the same process that holds the stream. So the API must run as **one process on one dyno**. Do not use `gunicorn --workers 2`, and do not scale to 2 dynos. Upgrade path: move the broker to Postgres `LISTEN/NOTIFY`.

### 3.3 Request a topic, approve it, generate questions

```mermaid
sequenceDiagram
    participant L as Learner
    participant Ad as Admin
    participant A as FastAPI
    participant D as Postgres
    participant W as Worker (run_once)
    participant C as Claude

    L->>A: POST /request-topic {topic_name}
    A->>D: insert pending_topics (queued)
    Ad->>A: GET /llm/admin/pending-requests
    Ad->>A: POST /llm/admin/approve-topic
    A->>D: insert llm_jobs (queued)
    A-->>Ad: 201
    A->>W: BackgroundTasks → run_once(1)
    W->>D: claim oldest queued job (FOR UPDATE SKIP LOCKED) → running
    W->>C: prompt: 20 questions, JSON
    C-->>W: JSON
    W->>W: validate with Pydantic (TopicQuestionsArtifact)
    W->>D: upsert questions (dedupe by hash), publish topic,<br/>delete pending row, job → succeeded
```

`SKIP LOCKED` makes two workers skip each other's rows. So the Scheduler and the in-process trigger can never pick up the same job.

### 3.4 Study Buddy chat (as built today)

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as FastAPI
    participant S as _SESSIONS dict<br/>(process memory)
    participant D as Postgres
    participant C as LLM

    B->>A: POST /study-buddy/sessions {mode, context}
    A->>D: insert study_sessions
    A->>S: cache state
    B->>A: POST /study-buddy/sessions/{id}/messages {message}
    A->>D: insert study_messages (user)
    A->>S: state.pending_message = message
    B->>A: GET /sse/study-buddy/{id}
    A->>S: pop pending_message
    A->>D: last 5 messages + the question (if context has question_id)
    A->>A: build prompt (+ mock "retrieved snippets")
    A->>C: one full request (no streaming)
    C-->>A: whole reply
    A-->>B: event: hint_meta, many event: token (60-char slices), event: done
    A->>D: insert study_messages (assistant), study_analytics
```

The UI side is `HintChat` (`edu-tech-ui/src/components/quiz-hint-chat.tsx`), a quiz-mode chat panel on the quiz page. It works, but it has several weak spots: fake streaming, mock snippets, and state kept in process memory. [learning/04-chatbot.md](learning/04-chatbot.md) walks through fixing each one.

## 4. Response shape

Most JSON endpoints wrap results in an envelope (`app/auth/schemas.Envelope`):

```json
{ "success": true, "data": { ... }, "meta": null }
```

Errors go through `app/utils/errors.py`. Every response carries an `X-Request-ID` header, which you can match against the logs.
