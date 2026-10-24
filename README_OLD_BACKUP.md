# Adaptive Quiz Backend (AWS + Supabase, low-cost)

> Skeleton-only repository for a FastAPI backend. Implements structure, configs, CI/linting, DB migrations, deploy assets, and typed stubs — **no business logic** yet.

**Tech baseline**
- Python 3.11, FastAPI (async), Uvicorn/Gunicorn
- Supabase Postgres (SQLAlchemy + Alembic)
- Background jobs via **systemd timer** (cron-style) on EC2
- Realtime via **Server-Sent Events (SSE)** endpoint scaffold
- Secrets via **sops + age** (no paid AWS Secrets Manager/Parameter Store)
- JSON logging, request ID middleware
- Quality: ruff, black, mypy, pytest, pre-commit

> This repo maps to the system design; each Python module includes a docstring like “Maps to Section X.Y of the design”. Business logic and external calls are intentionally stubbed with `NotImplementedError`.

---

## 1) Quickstart (Local)

```bash
# Python 3.11 recommended; use .python-version if you use pyenv
python -m venv .venv
source .venv/bin/activate
pip install -U pip

# Install project + dev tools
pip install -e ".[dev]"

# Copy env and edit as needed
cp .env.example .env
export $(grep -v '^#' .env | xargs)

# Run API locally (development)
python -m app.main
# or with Uvicorn explicitly:
# uvicorn app.main:app --reload --port 8000


---

```bash
## Module 1 (Quizzes Core) — Runbook

### 1) Migrate database
Applies Module 0 + Module 1 migrations (users.role, events.user_id, sessions adaptive fields).
```bash
alembic -c app/db/migrations/alembic.ini upgrade head

---

2) Start the API

uvicorn app.main:app --reload
# or in prod:
# /opt/adaptive/venv/bin/gunicorn -k uvicorn.workers.UvicornWorker app.main:app --bind 127.0.0.1:8000 --workers 2



3) Register / Login (get a token)

```bash
# register
curl -s http://127.0.0.1:8000/auth/register -H 'content-type: application/json' \
  -d '{"email":"u1@example.com","password":"StrongPass!","display_name":"U1"}' | jq

# or login (if already registered)
curl -s http://127.0.0.1:8000/auth/login -H 'content-type: application/json' \
  -d '{"email":"u1@example.com","password":"StrongPass!"}' | jq

# export token
TOKEN='<paste .data.access_token>'


4) Start a quiz session

You can pass topic_id or topic_name.

If topic_name doesn’t exist, a placeholder is created and a pending LLM job is queued (Module 3 will fulfill it).

```bash

curl -s http://127.0.0.1:8000/quizzes/start \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"topic_name":"Intro Algebra","difficulty_hint":3}' | jq

# capture session uid
SESSION=$(curl -s http://127.0.0.1:8000/quizzes/start \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"topic_name":"Intro Algebra"}' | jq -r .data.session.session_uid)
echo "$SESSION"


5) Stream realtime events (SSE)
# in a separate terminal:
curl -N "http://127.0.0.1:8000/quizzes/$SESSION/stream"
# you’ll see: event: heartbeat every 10s (configurable via SSE_HEARTBEAT_SECONDS)



6) Answer a question

You’ll need a real question_id (UUID) under the topic.

If your topic has no questions yet, the first_question will be null and needs_refill=true.

# example (adjust question_id)
curl -s "http://127.0.0.1:8000/quizzes/$SESSION/answer" \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"question_id":"00000000-0000-0000-0000-0000000000aa","selected_answer":"A","elapsed_ms":12000}' | jq
# SSE will emit:
#   event: answer
#   event: question   (if next question available)  OR
#   event: needs_refill


7) See summary

curl -s "http://127.0.0.1:8000/quizzes/$SESSION/summary" \
  -H "authorization: Bearer $TOKEN" | jq


---

Behavior & Invariants

Auth required for all quiz routes. Owners only; admins can inspect any session.

Start initializes: current_difficulty=3 (or hint), streak counters at zero, mastery_reached=false.

Answer:

Idempotent per (session_id, question_id) → returns 409 QZ409_DUPLICATE_ANSWER if repeated.

Streak of 3 correct raises difficulty by +1 (max 5).
Streak of 3 wrong lowers by −1 (min 1). Streak counters reset on opposite outcome.

mastery_reached becomes true when at difficulty 5 with a long correct streak (implementation conservatively checks high streak at 5).

Question selection uses (topic_id, difficulty) index and excludes already attempted questions for the session. Falls back to adjacent difficulties if empty; if none, needs_refill=true.

SSE streams heartbeats and events published after answers (answer, question, needs_refill, and summary).

Troubleshooting

401 Unauthenticated: missing/invalid Authorization: Bearer <token>.

403 Forbidden: attempting to access another user’s session with a non-admin token.

404 QZ404_SESSION_NOT_FOUND: bad session_uid.

409 QZ409_DUPLICATE_ANSWER: answering the same question twice within a session.

No first question: topic likely has no questions yet → needs_refill=true. Populate questions via admin tools / Module 2+3 flows.

Ops Notes (AWS EC2)

Nginx config at deploy/nginx/adaptive.conf already sets SSE headers (X-Accel-Buffering: no, Cache-Control: no-cache) and disables gzip on the SSE path.

Systemd units:

API: deploy/systemd/adaptive-api.service

Worker + timer: deploy/systemd/adaptive-worker.service / adaptive-worker.timer

Secrets via sops + age → decrypt to /etc/adaptive/env (0600).

Postgres is Supabase; ensure your DATABASE_URL uses TLS (e.g., ?sslmode=require).

Checklists
Security

JWT with role claim; issuer/audience validated.

require_auth() on all quiz endpoints; ownership enforced in service; admin override allowed.

Self-promotion blocked in Module 0; admin actions audited to events.

Performance

Selection query uses questions(topic_id, difficulty) index and excludes session-attempted rows.

Idempotency checked via single indexed lookup on attempts(session_id).

SSE queues are bounded; publisher is best-effort non-blocking.

Reliability

Multi-step writes occur in single transactions (answer path updates attempt + session + event).

SKIP LOCKED prevents contentions when multiple consumers exist.

Canonical errors mapped (401/403/404/409); clean JSON envelopes.

Observability

Structured logs include request_id, user_id, role, session_id, question_id, correctness, difficulty transitions.

Events table logs QUIZ_START and ATTEMPT_RECORDED.

API Quick Links

OpenAPI docs: http://127.0.0.1:8000/docs

Health: GET /healthz, GET /readyz

Auth: POST /auth/register, POST /auth/login

Quizzes: POST /quizzes/start, POST /quizzes/{session_uid}/answer, GET /quizzes/{session_uid}/summary, GET /quizzes/{session_uid}/stream

---