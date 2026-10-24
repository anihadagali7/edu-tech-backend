"""Admin-facing tests for Topics & Search (Module 2)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.jwt import generate_token
from app.utils.errors import TOP409_DUPLICATE_SLUG
from app.main import app


@pytest.mark.asyncio
async def test_admin_create_requires_admin_role() -> None:
    user_token = generate_token(subject="00000000-0000-0000-0000-000000000010", role="user")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {user_token}"}
    ) as client:
        r = await client.post("/admin/topics", json={"name": "Curated Topic"})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_create_and_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    admin_token = generate_token(subject="00000000-0000-0000-0000-000000000011", role="admin")

    from app.db.repositories import TopicRow
    row = TopicRow(
        id="t-curated",
        topic_uid="U-CUR",
        name="Curated Topic",
        slug="curated-topic",
        description=None,
        is_published=True,
        is_deleted=False,
    )

    import app.features.topics as T
    monkeypatch.setattr(T, "admin_create_topic", lambda db, **k: row)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {admin_token}"}
    ) as client:
        r = await client.post("/admin/topics", json={"name": "Curated Topic", "is_published": True})
        assert r.status_code == 201
        data = r.json()["data"]
        assert data["slug"] == "curated-topic"
        assert data["is_published"] is True


@pytest.mark.asyncio
async def test_admin_update_slug_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    admin_token = generate_token(subject="00000000-0000-0000-0000-000000000012", role="admin")

    import app.features.topics as T
    from app.utils.errors import AppError
    async def _update_conflict(**kwargs):
        raise AppError("duplicate slug", code=TOP409_DUPLICATE_SLUG, status=409)

    monkeypatch.setattr(T, "admin_update_topic", _update_conflict)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {admin_token}"}
    ) as client:
        r = await client.patch("/admin/topics/00000000-0000-0000-0000-000000000021", json={"slug": "taken"})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == TOP409_DUPLICATE_SLUG


@pytest.mark.asyncio
async def test_admin_import_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    admin_token = generate_token(subject="00000000-0000-0000-0000-000000000013", role="admin")

    import app.features.topics as T
    from app.db.repositories import TopicRow
    # Topic exists
    monkeypatch.setattr(
        T, "get_topic_by_id", lambda db, tid, include_deleted=False: TopicRow(
            id=str(tid),
            topic_uid="UT",
            name="Topic",
            slug="topic",
            description=None,
            is_published=True,
            is_deleted=False,
        )
    )
    monkeypatch.setattr(T, "bulk_upsert_questions", lambda db, topic_id, items: {"created_count": 3, "duplicate_count": 1})

    payload = {
        "topic_id": "00000000-0000-0000-0000-000000000031",
        "items": [
            {"body": "1+1?", "choices": {"A": "2", "B": "3"}, "correct_answer": "A", "difficulty": 1, "question_hash": "h1"},
            {"body": "2+2?", "choices": {"A": "3", "B": "4"}, "correct_answer": "B", "difficulty": 1, "question_hash": "h2"},
            {"body": "3*3?", "choices": {"A": "9", "B": "6"}, "correct_answer": "A", "difficulty": 2, "question_hash": "h3"},
            {"body": "dup", "choices": {"A": "x"}, "correct_answer": "A", "difficulty": 1, "question_hash": "h1"},
        ],
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {admin_token}"}
    ) as client:
        r = await client.post("/admin/questions/import", json=payload)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["created_count"] == 3
        assert data["duplicate_count"] == 1


@pytest.mark.asyncio
async def test_admin_delete_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    admin_token = generate_token(subject="00000000-0000-0000-0000-000000000014", role="admin")

    import app.features.topics as T
    monkeypatch.setattr(T, "admin_delete_topic", lambda db, topic_id, soft=True: None)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {admin_token}"}
    ) as client:
        r = await client.delete("/admin/topics/00000000-0000-0000-0000-000000000041")
        assert r.status_code == 200
        assert r.json()["data"]["deleted"] is True