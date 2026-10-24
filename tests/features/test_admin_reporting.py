"""Admin Reporting & Export tests (Module 4)."""

from __future__ import annotations

import io
import csv
import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.jwt import generate_token
from app.main import app


@pytest.mark.asyncio
async def test_rbac_non_admin_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    # Monkeypatch repos to prevent accidental DB hits
    import app.features.admin.reporting as R

    monkeypatch.setattr(R, "admin_list_users", lambda *a, **k: {"items": [], "total": 0})
    monkeypatch.setattr(R, "admin_list_events", lambda *a, **k: {"items": [], "total": 0})
    monkeypatch.setattr(R, "admin_snapshot_topics", lambda *a, **k: [])

    user_token = generate_token(subject="00000000-0000-0000-0000-000000000001", role="user")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"Authorization": f"Bearer {user_token}"}) as client:
        r1 = await client.get("/admin/users")
        r2 = await client.get("/admin/events")
        r3 = await client.get("/admin/export.json?type=users")
        assert r1.status_code == 403
        assert r2.status_code == 403
        assert r3.status_code == 403


@pytest.mark.asyncio
async def test_admin_users_list_envelope_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake_list_users(db, **filters):  # type: ignore[no-untyped-def]
        captured.update(filters)
        return {
            "items": [
                {
                    "id": "u1",
                    "email": "a@example.com",
                    "display_name": "Alice",
                    "role": "user",
                    "created_at": "2025-09-01T00:00:00+00:00",
                },
                {
                    "id": "u2",
                    "email": "b@example.com",
                    "display_name": "Bob",
                    "role": "admin",
                    "created_at": "2025-09-02T00:00:00+00:00",
                },
            ],
            "total": 2,
        }

    import app.features.admin.reporting as R

    monkeypatch.setattr(R, "admin_list_users", fake_list_users)

    admin_token = generate_token(subject="00000000-0000-0000-0000-0000000000aa", role="admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"Authorization": f"Bearer {admin_token}"}) as client:
        r = await client.get("/admin/users?q=ali&role=admin&created_from=2025-01-01T00:00:00+00:00&limit=2&offset=0")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data["limit"] == 2 and data["offset"] == 0 and data["total"] == 2
        assert len(data["items"]) == 2
        # Filters are parsed and forwarded
        assert captured["q"] == "ali"
        assert captured["role"] == "admin"
        assert captured["limit"] == 2
        assert captured["offset"] == 0


@pytest.mark.asyncio
async def test_admin_events_list_with_time_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake_list_events(db, **filters):  # type: ignore[no-untyped-def]
        captured.update(filters)
        return {
            "items": [
                {
                    "id": "e1",
                    "user_id": "00000000-0000-0000-0000-0000000000aa",
                    "session_id": None,
                    "event_type": "QUIZ_START",
                    "payload": {"topic_id": "t1"},
                    "created_at": "2025-09-19T12:00:00+00:00",
                }
            ],
            "total": 1,
        }

    import app.features.admin.reporting as R

    monkeypatch.setattr(R, "admin_list_events", fake_list_events)

    admin_token = generate_token(subject="00000000-0000-0000-0000-0000000000ab", role="admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"Authorization": f"Bearer {admin_token}"}) as client:
        r = await client.get("/admin/events?event_type=QUIZ_START&from_ts=2025-09-01T00:00:00+00:00&limit=1")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["event_type"] == "QUIZ_START"
        # Ensure filters forwarded (presence is enough; values are datetime objects)
        assert "from_ts" in captured and "event_type" in captured
        assert captured["limit"] == 1


@pytest.mark.asyncio
async def test_admin_export_json_users(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list_users(db, **filters):  # type: ignore[no-untyped-def]
        return {
            "items": [{"id": "u1", "email": "x@example.com", "display_name": None, "role": "user", "created_at": None}],
            "total": 1,
        }

    import app.features.admin.reporting as R

    monkeypatch.setattr(R, "admin_list_users", fake_list_users)

    admin_token = generate_token(subject="00000000-0000-0000-0000-0000000000ac", role="admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"Authorization": f"Bearer {admin_token}"}) as client:
        r = await client.get("/admin/export.json?type=users&limit=10")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["success"] is True
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["email"] == "x@example.com"


@pytest.mark.asyncio
async def test_admin_export_csv_topics(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_snapshot_topics(db, include_unpublished=False):  # type: ignore[no-untyped-def]
        return [
            {
                "id": "t1",
                "topic_uid": "U1",
                "name": "Intro Algebra",
                "slug": "intro-algebra",
                "description": None,
                "is_published": True,
                "created_at": "2025-09-01T00:00:00+00:00",
                "updated_at": "2025-09-02T00:00:00+00:00",
            }
        ]

    import app.features.admin.reporting as R

    monkeypatch.setattr(R, "admin_snapshot_topics", fake_snapshot_topics)

    admin_token = generate_token(subject="00000000-0000-0000-0000-0000000000ad", role="admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"Authorization": f"Bearer {admin_token}"}) as client:
        r = await client.get("/admin/export.csv?type=topics&limit=10")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        # Parse CSV
        buf = io.StringIO(r.text)
        reader = csv.reader(buf)
        header = next(reader)
        row = next(reader)
        assert "slug" in header
        assert "intro-algebra" in ",".join(row)
