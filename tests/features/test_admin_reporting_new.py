"""Test cases for admin reporting endpoints."""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.features.admin.reporting import admin_events_count, admin_questions_count
from app.db.repositories import count_total_questions, admin_list_events


class TestAdminEventsCountEndpoint:
    """Test cases for /admin/events/count endpoint."""

    @pytest.mark.asyncio
    async def test_admin_events_count_success(self):
        """Test successful events count retrieval."""
        # Mock data
        mock_events_data = {
            "items": [
                {
                    "id": "event-1",
                    "user_id": "user-1",
                    "session_id": "session-1",
                    "event_type": "login",
                    "payload": {"action": "login"},
                    "created_at": "2024-01-01T00:00:00Z",
                }
            ],
            "total": 1,
        }

        # Mock dependencies
        mock_user = {"role": "admin"}
        mock_db = AsyncMock(spec=AsyncSession)

        with patch("app.features.admin.reporting.admin_list_events", return_value=mock_events_data):
            result = await admin_events_count(
                request=AsyncMock(),
                user=mock_user,
                db=mock_db,
            )

        assert result.data == {"total": 1}

    @pytest.mark.asyncio
    async def test_admin_events_count_empty(self):
        """Test events count when no events exist."""
        mock_events_data = {"items": [], "total": 0}

        mock_user = {"role": "admin"}
        mock_db = AsyncMock(spec=AsyncSession)

        with patch("app.features.admin.reporting.admin_list_events", return_value=mock_events_data):
            result = await admin_events_count(
                request=AsyncMock(),
                user=mock_user,
                db=mock_db,
            )

        assert result.data == {"total": 0}

    @pytest.mark.asyncio
    async def test_admin_events_count_large_number(self):
        """Test events count with large number of events."""
        mock_events_data = {"items": [], "total": 1000}

        mock_user = {"role": "admin"}
        mock_db = AsyncMock(spec=AsyncSession)

        with patch("app.features.admin.reporting.admin_list_events", return_value=mock_events_data):
            result = await admin_events_count(
                request=AsyncMock(),
                user=mock_user,
                db=mock_db,
            )

        assert result.data == {"total": 1000}


class TestAdminQuestionsCountEndpoint:
    """Test cases for /admin/questions/count endpoint."""

    @pytest.mark.asyncio
    async def test_admin_questions_count_success(self):
        """Test successful questions count retrieval."""
        mock_user = {"role": "admin"}
        mock_db = AsyncMock(spec=AsyncSession)

        with patch("app.features.admin.reporting.count_total_questions", return_value=42):
            result = await admin_questions_count(
                request=AsyncMock(),
                user=mock_user,
                db=mock_db,
            )

        assert result.data == {"total": 42}

    @pytest.mark.asyncio
    async def test_admin_questions_count_zero(self):
        """Test questions count when no questions exist."""
        mock_user = {"role": "admin"}
        mock_db = AsyncMock(spec=AsyncSession)

        with patch("app.features.admin.reporting.count_total_questions", return_value=0):
            result = await admin_questions_count(
                request=AsyncMock(),
                user=mock_user,
                db=mock_db,
            )

        assert result.data == {"total": 0}

    @pytest.mark.asyncio
    async def test_admin_questions_count_large_number(self):
        """Test questions count with large number of questions."""
        mock_user = {"role": "admin"}
        mock_db = AsyncMock(spec=AsyncSession)

        with patch("app.features.admin.reporting.count_total_questions", return_value=5000):
            result = await admin_questions_count(
                request=AsyncMock(),
                user=mock_user,
                db=mock_db,
            )

        assert result.data == {"total": 5000}


class TestTopicsEndpointWithTotal:
    """Test cases for updated /topics endpoint with total count."""

    @pytest.mark.asyncio
    async def test_topics_endpoint_includes_total(self):
        """Test that topics endpoint includes total count in response."""
        from app.features.topics import list_topics

        mock_topics_data = {
            "items": [
                {
                    "id": "topic-1",
                    "topic_uid": "uid-1",
                    "name": "Test Topic",
                    "slug": "test-topic",
                    "description": "A test topic",
                    "is_published": True,
                    "is_deleted": False,
                }
            ],
            "total": 1,
        }

        mock_user = {"role": "user"}
        mock_db = AsyncMock(spec=AsyncSession)

        with patch("app.features.topics.repo_list_topics", return_value=mock_topics_data), \
             patch("app.features.topics.count_questions_by_topic", return_value=5):
            result = await list_topics(
                request=AsyncMock(),
                q=None,
                limit=50,
                offset=0,
                db=mock_db,
            )

        assert result.data["total"] == 1
        assert len(result.data["items"]) == 1
        assert result.data["items"][0]["question_count"] == 5

    @pytest.mark.asyncio
    async def test_topics_endpoint_with_search_includes_total(self):
        """Test that topics endpoint with search includes total count."""
        from app.features.topics import list_topics

        mock_topics_data = {
            "items": [
                {
                    "id": "topic-1",
                    "topic_uid": "uid-1",
                    "name": "Math Topic",
                    "slug": "math-topic",
                    "description": "A math topic",
                    "is_published": True,
                    "is_deleted": False,
                }
            ],
            "total": 1,
        }

        mock_user = {"role": "user"}
        mock_db = AsyncMock(spec=AsyncSession)

        with patch("app.features.topics.repo_list_topics", return_value=mock_topics_data), \
             patch("app.features.topics.count_questions_by_topic", return_value=10):
            result = await list_topics(
                request=AsyncMock(),
                q="math",
                limit=50,
                offset=0,
                db=mock_db,
            )

        assert result.data["total"] == 1
        assert len(result.data["items"]) == 1
        assert result.data["items"][0]["name"] == "Math Topic"

    @pytest.mark.asyncio
    async def test_topics_endpoint_pagination_with_total(self):
        """Test that topics endpoint pagination includes correct total."""
        from app.features.topics import list_topics

        mock_topics_data = {
            "items": [
                {
                    "id": "topic-2",
                    "topic_uid": "uid-2",
                    "name": "Science Topic",
                    "slug": "science-topic",
                    "description": "A science topic",
                    "is_published": True,
                    "is_deleted": False,
                }
            ],
            "total": 25,  # Total across all pages
        }

        mock_user = {"role": "user"}
        mock_db = AsyncMock(spec=AsyncSession)

        with patch("app.features.topics.repo_list_topics", return_value=mock_topics_data), \
             patch("app.features.topics.count_questions_by_topic", return_value=15):
            result = await list_topics(
                request=AsyncMock(),
                q=None,
                limit=10,
                offset=10,  # Second page
                db=mock_db,
            )

        assert result.data["total"] == 25  # Total should be across all pages
        assert len(result.data["items"]) == 1  # Only 1 item on this page
        assert result.data["limit"] == 10
        assert result.data["offset"] == 10
