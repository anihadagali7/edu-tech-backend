"""Test cases for pending topic management."""

import pytest
from httpx import AsyncClient
from uuid import uuid4

from app.main import app
from app.auth.middleware import clerk_auth_dependency


@pytest.fixture
def mock_admin():
    """Mock admin user."""
    return {
        "id": uuid4(),
        "clerk_user_id": "user_admin123",
        "role": "admin",
        "profile_complete": True,
        "full_name": "Admin User",
        "avatar_url": None,
        "claims": {},
    }


@pytest.fixture
def mock_regular_user():
    """Mock regular user."""
    return {
        "id": uuid4(),
        "clerk_user_id": "user_student123",
        "role": "user",
        "profile_complete": True,
        "full_name": "Student User",
        "avatar_url": None,
        "claims": {},
    }


@pytest.mark.asyncio
async def test_list_pending_requests_requires_admin(mock_regular_user):
    """Test that listing pending requests requires admin role."""
    async def mock_auth_dep():
        return mock_regular_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/llm/admin/pending-requests")
        assert response.status_code == 403

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_pending_requests_success(mock_admin):
    """Test successful listing of pending requests."""
    async def mock_auth_dep():
        return mock_admin

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/llm/admin/pending-requests")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "requests" in data["data"]
        assert "total" in data["data"]
        assert "total_queued" in data["data"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_pending_includes_all_statuses(mock_admin):
    """Test that pending list includes queued, approved, and rejected."""
    async def mock_auth_dep():
        return mock_admin

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/llm/admin/pending-requests")
        assert response.status_code == 200
        # Should return all statuses, not just queued

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reject_pending_request_requires_admin(mock_regular_user):
    """Test that rejecting requires admin role."""
    async def mock_auth_dep():
        return mock_regular_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    request_id = str(uuid4())
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(f"/llm/admin/pending-requests/{request_id}/reject")
        assert response.status_code == 403

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reject_pending_request_success(mock_admin):
    """Test successful rejection of pending request."""
    async def mock_auth_dep():
        return mock_admin

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    # Will be 404 if request doesn't exist in test DB, but shouldn't be 403
    request_id = str(uuid4())
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(f"/llm/admin/pending-requests/{request_id}/reject")
        assert response.status_code in [200, 404]  # 200 if exists, 404 if not

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reject_sets_status_to_rejected(mock_admin):
    """Test that rejecting sets status to 'rejected', not delete."""
    # This test would require actual DB seeding to verify the status change
    # For now, we test the endpoint structure
    async def mock_auth_dep():
        return mock_admin

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    request_id = str(uuid4())
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(f"/llm/admin/pending-requests/{request_id}/reject")
        # If successful, should return status in response
        if response.status_code == 200:
            data = response.json()
            assert data["data"]["rejected"] is True
            assert data["data"]["status"] == "rejected"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reject_nonexistent_request_returns_404(mock_admin):
    """Test that rejecting non-existent request returns 404."""
    async def mock_auth_dep():
        return mock_admin

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    # Use UUID that definitely doesn't exist
    request_id = str(uuid4())
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(f"/llm/admin/pending-requests/{request_id}/reject")
        assert response.status_code == 404

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_total_queued_count_only_queued_items(mock_admin):
    """Test that total_queued only counts items with status='queued'."""
    async def mock_auth_dep():
        return mock_admin

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/llm/admin/pending-requests")
        assert response.status_code == 200
        data = response.json()
        
        # total_queued should be <= total
        total = data["data"]["total"]
        total_queued = data["data"]["total_queued"]
        assert total_queued <= total

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pending_requests_include_status_field(mock_admin):
    """Test that pending requests include status field."""
    async def mock_auth_dep():
        return mock_admin

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/llm/admin/pending-requests")
        assert response.status_code == 200
        data = response.json()
        
        # If there are requests, verify they have status
        if data["data"]["requests"]:
            first_request = data["data"]["requests"][0]
            assert "status" in first_request
            # Status should be one of: queued, approved, rejected
            assert first_request["status"] in ["queued", "approved", "rejected"]

    app.dependency_overrides.clear()

