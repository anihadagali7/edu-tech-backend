# Platform decisions (2026 revival)

Constraints: hobby budget, no AWS, start from new accounts. Heroku and Vercel accounts already exist.

Prices below were checked in October 2026 from third-party summaries. Confirm them on each vendor's pricing page when you sign up.

## Summary

| Need | Before (2025) | Now | Monthly cost |
|---|---|---|---|
| UI hosting | AWS Amplify | **Vercel** (Hobby) | $0 |
| API hosting | AWS EC2 + nginx + systemd | **Heroku**, 1 Basic dyno | ~$7 (Eco: $5, but it sleeps) |
| Background jobs | systemd timer every 2 min | **In-process trigger + Heroku Scheduler** | ~$0 (Scheduler runs short one-off dynos) |
| Database | Supabase Postgres | **Neon** Postgres (Free) | $0 |
| Auth | Clerk | **Clerk** (new account, free Hobby plan) | $0 |
| LLM | OpenAI GPT-4 via LangChain | **Claude** via the official `anthropic` SDK | pay per token |
| File storage | S3 (optional) | **None.** Drop it. | $0 |

Expected fixed cost: **about $7 a month**, plus Claude usage.

## 1. UI → Vercel

- The UI is Next.js, and Vercel makes Next.js. You connect the GitHub repo and every push deploys. Pull requests get preview URLs.
- The UI is a plain browser app. It has no server-side database work and no long-running requests, so the free Hobby plan's limits do not matter here.
- Hobby is for non-commercial use. If this ever earns money, move to Pro.
- Remove `amplify.yml`, `Dockerfile`, `ecs-task-definition.json` and `DEPLOYMENT.md` (all AWS-only).

## 2. API → Heroku

Why not run the Python API on Vercel too?

- The quiz and the chatbot use **Server-Sent Events** (SSE: the server keeps one HTTP response open and pushes messages down it). Vercel functions are short-lived and are not built for streams that stay open for minutes.
- The quiz keeps live sessions in process memory, and the job runner works inside the web process. Both need **one long-running process**, which is exactly what a Heroku dyno is.

Heroku details that matter for this code:

- **Run one process.** Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. No `--workers`, and no second dyno, because of the in-memory quiz broker ([architecture.md §3.2](architecture.md#32-take-an-adaptive-quiz-live-stream)).
- **The 55-second rule.** Heroku closes a connection that is quiet for 55 seconds. The quiz stream sends a heartbeat every 10 s (`SSE_HEARTBEAT_SECONDS`), so it stays open.
- **Eco or Basic?** Eco ($5) sleeps after 30 minutes with no traffic, and the first request then takes 5–15 s to wake it. Fine while you build alone. Switch to Basic ($7, always on) when you share the app.
- **Scheduler** (free add-on, billed as dyno time): every 10 minutes, run `python run_worker.py`. It finishes any job the web process dropped during a restart.

## 3. Database → Neon

The code needs real Postgres. It uses `JSONB`, `gen_random_uuid()`, enums, `FOR UPDATE SKIP LOCKED` and GIN indexes, so SQLite and other "Postgres-like" stores are out.

| Option | Free tier | Notes |
|---|---|---|
| **Neon** ✅ | 0.5 GB storage, ~100 compute-hours per month, no card, no expiry | Pauses after 5 min idle; the first query after that adds a short cold start. Has `pgvector` for later chatbot search. Branches give you a throwaway copy of the database for testing a migration. |
| Heroku Postgres | none (Essential-0 is ~$5/mo) | Simplest to wire up (`DATABASE_URL` set for you), but it costs money and has no branches. |
| Supabase | free, but pauses the project after a week without use | We would use only its database, and the pausing is annoying for a hobby app. |

**Pick Neon.** It is free, real Postgres, and has room to grow.

Connection notes for Neon:

- Use the **direct** connection string, not the `-pooler` one. The app uses asyncpg, which caches prepared statements. Neon's pooler runs PgBouncer in transaction mode, and that breaks those statements. With one dyno and `pool_size=5`, direct connections are well within the limits.
- Set `DATABASE_URL=postgresql+asyncpg://…neon.tech/neondb?sslmode=require`. Alembic changes this to a psycopg URL, and psycopg reads `sslmode`. **But today the app drops the whole query string.** `app/db/base.py` removes it and never passes SSL on, so Neon refuses the connection. Also, `llm/worker.py` builds its own engine from the raw URL, and asyncpg does not accept `sslmode`. Both are fixed in [revival-plan.md](revival-plan.md) step 2.

## 4. Auth → Clerk (keep)

- About 15 files in the UI and the API's whole auth layer are written for Clerk. Swapping it would be the biggest change in the project and would buy nothing.
- The free Hobby plan covers 50,000 monthly retained users (raised from 10,000 in February 2026).
- Delete the unused NextAuth, Prisma and bcrypt leftovers from the UI (see [revival-plan.md](revival-plan.md)).

## 5. LLM → Claude

- Use the official **`anthropic` Python SDK** directly and **remove LangChain**. Today LangChain is used only to send a list of messages and read back text. The SDK does that in the same number of lines, and it gives you streaming, tool use, structured output and prompt caching with no translation layer. It is also easier to learn from.
- **Model:** `claude-opus-5-5` (Claude Opus 5.5, $4 in / $20 out per million tokens) is the default for both question writing and the tutor. Keep it in an env var, `CLAUDE_MODEL`, so you can switch per environment. Cheaper options, if you want them later: `claude-sonnet-5-5` ($2 / $10) and `claude-haiku-5-5` ($0.10 / $0.50).
- **Rough cost:** one 20-question generation job is about 2k tokens in and 8k out, so about **$0.17 per topic** on Opus 5.5. A tutor reply is about 2k in and 300 out, so about **$0.014**. A hundred topics and a thousand chat turns come to under $35.
- Set a monthly spend limit in the Claude Console on day one.

## 6. File storage → none

`llm/worker.py` uploads each raw LLM reply to S3 only if `S3_BUCKET` is set. The questions are already saved in Postgres, so the upload is only a backup copy. Leave `S3_BUCKET` unset, and later delete `_maybe_upload_s3` and the `boto3` requirement. If you ever want the raw replies, store them in a `jsonb` column on `llm_jobs`.

## Not chosen, and why

- **Render / Railway / Fly.io** for the API: all would work. Heroku wins only because the account already exists.
- **One host for both** (for example, everything on Heroku): possible, but Vercel's Next.js previews and build caching are free and better.
- **OpenAI-compatible shims for Claude:** rejected. Use the native SDK, so features like prompt caching and tool use work as documented.
