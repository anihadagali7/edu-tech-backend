"""User-facing tests for Topics & Search (Module 2)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.jwt import generate_token
from app.main import app


@pytest.mark.asyncio
async def test_list_topics_published(monkeypatch: pytest.MonkeyPatch) -> None:
    # Monkeypatch repo_list_topics to return two published topics
    from app.db.repositories import TopicRow

    rows = [
        TopicRow(
            id="t1",
            topic_uid="U1",
            name="Intro Algebra",
            slug="intro-algebra",
            description=None,
            is_published=True,
            is_deleted=False,
        ),
        TopicRow(
            id="t2",
            topic_uid="U2",
            name="Physics",
            slug="physics",
            description=None,
            is_published=True,
            is_deleted=False,
        ),
    ]

    import app.features.topics as T
    monkeypatch.setattr(T, "repo_list_topics", lambda *a, **k: rows)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/topics?q=algebra")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert len(body["data"]["items"]) == 2
        assert body["data"]["items"][0]["slug"] == "intro-algebra"


@pytest.mark.asyncio
async def test_get_topic_404_when_unpublished(monkeypatch: pytest.MonkeyPatch) -> None:
    # Return a topic that is NOT published -> 404
    from app.db.repositories import TopicRow

    topic = TopicRow(
        id="00000000-0000-0000-0000-000000000001",
        topic_uid="U1",
        name="Hidden",
        slug="hidden",
        description=None,
        is_published=False,
        is_deleted=False,
    )

    import app.features.topics as T
    monkeypatch.setattr(T, "get_topic_by_id", lambda db, tid: topic)
    monkeypatch.setattr(T, "count_questions_by_topic", lambda db, tid: 0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/topics/{topic.id}")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "TOP404_NOT_FOUND"


@pytest.mark.asyncio
async def test_search_enqueue_on_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    # No matches -> enqueue pending + job
    import app.features.topics as T
    monkeypatch.setattr(T, "repo_list_topics", lambda *a, **k: [])
    monkeypatch.setattr(
        T,
        "upsert_pending_topic_and_job",
        lambda db, topic_slug, display_name, requested_by: {"pending_topic": {"topic_slug": topic_slug}, "job_id": "job-1"},
    )

    token = generate_token(subject="00000000-0000-0000-0000-000000000002", role="user")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        r = await client.get("/search?q=New Fancy Topic")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["matches"] == []
        assert data["enqueued"]["pending_topic"]["topic_slug"] == "new-fancy-topic"
        assert data["enqueued"]["job_id"] == "job-1"