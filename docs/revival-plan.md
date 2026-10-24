# Revival plan

These are the code changes needed before the app can run on the [chosen platforms](decisions.md). They are listed in order, and each step can be checked before you start the next. Steps 1–3 make the API boot. Step 4 swaps OpenAI for Claude. Step 5 is the UI. Then follow [deployment.md](deployment.md).

Every item below was found by reading the code. None of it has been run against Neon or Heroku yet.

## Step 1: Remove dead weight

Neither repo needs any of this. Removing it first makes the later diffs smaller.

**Backend**

- [ ] Delete the one-off scripts at the repo root: `test_*.py`, `check_*.py`, `debug_role_issue.py`, `fix_migration.py`, `reset_migration.py`, `revert_*.py`, `set_admin.py`, `verify_fixes.py`, `cleanup_files.py`, `add_org_columns.py`. The real tests live in `tests/`.
- [ ] Delete the 2025 status notes at the root: `*_SUMMARY.md`, `*_COMPLETE.md`, `*_STATUS.md`, `SSE_*.md`, `STUDY_BUDDY_*.md`, `YOUR_QUESTIONS_ANSWERED.md`, `README_OLD_BACKUP.md`, `*_ROLES*.md`, `LLM_AUTOMATION_GUIDE.md`, `AUTOMATIC_WORKER.md`, `API_QUICK_REFERENCE.md`. Their useful content is now in `docs/`.
- [ ] Delete `clerk-min/` (a Vite test app with an old Clerk publishable key), `deploy/` (EC2/nginx/systemd/sops) and `package.json` (only `@clerk/clerk-react`, which nothing uses).
- [ ] Delete `worker/` and `tests/test_worker_smoke.py`. This is the older second worker. The live worker is `app/features/llm/worker.py`.

**UI**

- [x] Delete `amplify.yml`, `Dockerfile`, `ecs-task-definition.json`, `DEPLOYMENT.md`, `prisma/` and `postcss.config.mjs` (a duplicate of `postcss.config.js`).
- [x] Remove the unused packages: `npm uninstall @auth/prisma-adapter @prisma/client prisma next-auth bcryptjs @types/bcryptjs`. Also remove the four `db:*` scripts. Nothing in `src/` imports any of them.
- [x] Replace `env.example` with the real variables (see [deployment.md](deployment.md#ui-env-vars)).

## Step 2: Make the API boot on Heroku + Neon

| # | Problem | Where | Fix |
|---|---|---|---|
| 2a | Heroku's Python buildpack looks for `requirements.txt`. The file here is named `requirements`, without the extension. | repo root | `git mv requirements requirements.txt`. Add `.python-version` with `3.11` (from `pyproject.toml`). |
| 2b | No `Procfile`. | repo root | Two lines: `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT` and `release: alembic upgrade head`. One process only (see [decisions.md §2](decisions.md#2-api--heroku)). |
| 2c | CORS origins are hardcoded to localhost, so the Vercel site would be blocked. The env var is read in a commented-out line. | `app/config.py` `from_env` | `"CORS_ORIGINS": get_list("CORS_ORIGINS", ["http://localhost:3000"])`. Note that `get_list` lowercases values, which is fine for origins. |
| 2d | The DB URL query string is dropped, so SSL is never turned on and Neon refuses the connection. | `app/db/base.py` | When the query has `sslmode` (or `ssl`), set `connect_args["ssl"] = "require"`. |
| 2e | The worker builds a brand-new engine from the raw URL on every run. asyncpg rejects `sslmode`, and each run leaks a connection pool. | `app/features/llm/worker.py` `run_once` | Use `SessionLocal` from `app.db.base` instead of `create_async_engine(...)`. This deletes code. |
| 2f | ~~Alembic has two heads.~~ **Done** in `0011_merge_heads`; the head is now `0012_link_quiz_to_uid`. | `app/db/migrations/versions` | Still to do: run `alembic upgrade head` once on a clean Neon branch ([database.md §3](database.md#3-migrations-on-a-fresh-database)). |
| 2g | The Clerk webhook reads `settings.CLERK_WEBHOOK_SECRET`, which is not defined on `Settings`, so any call fails with an error. The webhook is not needed anyway, because users are upserted on every request. | `app/auth/clerk_webhooks.py`, `app/main.py` | Unmount the webhook router and delete the file. Also remove `svix` from requirements. |
| 2h | `/dev/topics-noauth` is mounted in production ("DEV ONLY - Remove in production"). It only lists published topics, so the risk is low, but it is still an unauthenticated route. | `app/api/routes.py` | Delete the route and `app/features/dev_routes.py`. |
| 2i | With `LLM_PROVIDER` unset, `_call_llm_generate` returns `None`, and every job fails with a confusing validation error. | `app/features/llm/worker.py` | This goes away in step 4. |

**Status (2026-10-24):** 2a–2e, 2g and 2h are done. 2f still needs one run against Neon, and 2i waits for step 4.

Check: `alembic heads` prints one line, `uvicorn app.main:app` starts locally against a Neon branch, and `GET /health` returns `healthy`.

**Test suite:** 106 of 159 tests fail, both before and after step 2, so the failures were already there. The main causes: newer `httpx` dropped `AsyncClient(app=...)` (24 tests; use `ASGITransport`), tests that need a local Postgres on port 5432 (15), and tests written for older function signatures (`org_id`, `topic_uid`, UUID handling). Fixing them is a separate task. Until then, don't treat a red test run as a signal.

## Step 3: Clerk setup the code expects

- The API checks the token's issuer (`CLERK_ISSUER`) and fetches keys from `CLERK_JWKS_URL`. Both are shown on the Clerk dashboard's API Keys page.
- **The admin role must be in the session token.** The API reads `claims["role"]` or `claims["public_metadata"]["role"]`. In Clerk, go to **Sessions → Customize session token** and add `{"role": "{{user.public_metadata.role}}"}`. Then set `{"role": "admin"}` in your own user's public metadata, and sign out and back in.
- Leave **Organizations** turned off.

## Step 4: OpenAI → Claude

Four places call an LLM today. All four go through LangChain.

| Caller | File | What it does |
|---|---|---|
| Question generator | `app/features/llm/provider_openai.py` (called from `worker._call_llm_generate`) | 20 multiple-choice questions as JSON |
| Learning materials | `app/features/llm/handler_learning_materials.py` `_call_openai_for_materials` | Sections of study notes as JSON, with a "repair" retry |
| Study Buddy | `app/features/study_buddy/service.py` `_get_llm_client` / `_call_llm` | One tutor reply as text |
| Legacy worker | `worker/runner.py` | Deleted in step 1 |

Plan:

1. `pip install anthropic` and add it to `requirements.txt`. Remove `langchain`, `langchain-openai`, `langchain-core`, `langchain-text-splitters`, `openai` and `tiktoken`.
2. Settings: replace `OPENAI_API_KEY` / `OPENAI_MODEL` with `ANTHROPIC_API_KEY` / `CLAUDE_MODEL` (default `claude-opus-5-5`). Remove the `LLM_PROVIDER`, `STUDY_BUDDY_USE_OPENAI`, `STUDY_BUDDY_MODEL` and `LEARNING_MATERIAL_MODEL` switches. Keep a single `LLM_PROVIDER=mock` option for tests and offline work.
3. Replace `provider_openai.py` with `provider_claude.py`. Structured output replaces the JSON-mode list, the fence stripping and most of the normalizing code. A sketch:

   ```python
   import anthropic
   from app.features.llm.schema import TopicQuestionsArtifact

   _client = anthropic.AsyncAnthropic()  # reads ANTHROPIC_API_KEY

   async def generate_questions(topic_slug: str, n: int, *, topic_name=None, topic_description=None) -> dict:
       system, user = build_question_prompt(topic_slug, n, topic_name, topic_description)  # plain strings
       response = await _client.messages.parse(
           model=get_settings().CLAUDE_MODEL,
           max_tokens=16000,
           system=system,
           messages=[{"role": "user", "content": user}],
           output_format=TopicQuestionsArtifact,
       )
       return response.parsed_output.model_dump(mode="json")
   ```

   `prompts/llm_topic_questions.py` and `app/features/llm/prompt.py` build LangChain message objects today. Change them to return plain `(system, user)` strings.
4. Learning materials: do the same with `messages.parse`, and delete the repair round-trip.
5. Study Buddy: swap the client, then follow [learning/04-chatbot.md](learning/04-chatbot.md) for real streaming and history.
6. Tests: update `tests/features/test_llm_provider.py` and `tests/features/test_worker_provider_delegate.py` to mock `anthropic.AsyncAnthropic`. They should check that a bad reply marks the job `failed`.

**Drop `temperature`.** The old code sets `temperature=0.2` (questions) and `0.6` (tutor). Since 2026-10-21, the Claude API rejects `temperature`, `top_p` and `top_k` on every model with a 400 error. Use `output_config={"effort": ...}` to trade depth for speed instead.

One thing to check: some Pydantic constraints in `schema.py` (`min_length`, `max_length` on lists and strings) may not be enforceable by structured outputs. The SDK still validates the reply after it arrives, so a reply that breaks a rule raises an error and marks the job failed. Run one real job and watch for this.

## Step 5: UI

- [ ] Set the Vercel env vars ([deployment.md](deployment.md#ui-env-vars)).
- [ ] `src/app/api/subjects/route.ts` returns hardcoded subjects with a fake 500 ms delay. `src/contexts/app-context.tsx` calls it. Keep it as a static list but drop the delay, or move the list into the context and delete the route.
- [ ] Rewrite the README (done in this pass).

## Step 6: After it is live

- [ ] Turn on `ENABLE_STUDY_BUDDY=1`. The quiz page's `HintChat` panel starts working. Then follow [learning/04-chatbot.md](learning/04-chatbot.md).
- [ ] Replace the in-memory quiz broker with Postgres `LISTEN/NOTIFY` if you ever need a second dyno.
- [ ] `auto_worker.is_processing` skips a trigger while another job is running. The second job then waits for the 10-minute Scheduler run. If that delay bothers you, loop `run_once` until the queue is empty.
