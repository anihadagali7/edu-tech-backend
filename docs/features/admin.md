# Admin panel

**In one line:** pages under `/admin` in the UI, backed by `admin`-role endpoints in the API.

| UI page | What it shows / does | API |
|---|---|---|
| `/admin` | counts: users, topics, questions, events | `GET /admin/users`, `GET /topics`, `GET /admin/questions/count`, `GET /admin/events/count` |
| `/admin/topics` | all topics, pending requests, approve / reject, create, edit, delete | `POST /admin/topics`, `PATCH`/`DELETE /admin/topics/{id}`, `GET /llm/admin/pending-requests`, `POST /llm/admin/approve-topic`, `POST /llm/admin/pending-requests/{id}/reject`, `POST /llm/admin/create-topic` |
| `/admin/jobs` | LLM job queue with status, error and created count | `GET /llm/admin/jobs` |
| `/admin/users` | users and their quiz stats | `GET /admin/users` |
| `/admin/events` | the audit log, filterable | `GET /admin/events` |
| (no page) | CSV or JSON export | `GET /admin/export.csv`, `GET /admin/export.json` |
| (no page) | bulk question import | `POST /admin/questions/import` |

Code: `app/features/admin/reporting.py`, `app/features/topics.py` (admin section), `app/features/llm/jobs.py`. UI: `src/app/admin/**`, with tests in each folder's `__tests__/`.

`DELETE /admin/topics/{id}` is a soft delete by default: it sets `is_deleted` and hides the topic, and questions and history stay. Use `?soft=false` to remove the topic for real.
