"""Test cases for user profile management endpoints."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.main import app
from app.auth.middleware import clerk_auth_dependency


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    return {
        "id": uuid4(),
        "clerk_user_id": "user_test123",
        "role": "user",
        "profile_complete": False,
        "age": None,
        "highest_education_level": None,
        "subjects_of_interest": [],
        "full_name": "Test User",
        "avatar_url": None,
        "claims": {},
    }


@pytest.fixture
def mock_completed_user():
    """Mock user with completed profile."""
    return {
        "id": uuid4(),
        "clerk_user_id": "user_test456",
        "role": "user",
        "profile_complete": True,
        "age": 12,
        "highest_education_level": "middle-school",
        "subjects_of_interest": ["mathematics", "science"],
        "full_name": "Test User",
        "avatar_url": None,
        "claims": {},
    }


@pytest.mark.asyncio
async def test_get_profile_requires_auth():
    """Test that GET /profile requires authentication."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/profile")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_profile_requires_auth():
    """Test that PUT /profile requires authentication."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.put(
            "/profile",
            json={
                "age": 12,
                "highest_education_level": "middle-school",
                "subjects_of_interest": ["mathematics"],
            },
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_profile_success(mock_user, monkeypatch):
    """Test successful profile update."""
    # Mock authentication
    async def mock_auth_dep():
        return mock_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.put(
            "/profile",
            json={
                "age": 12,
                "highest_education_level": "middle-school",
                "subjects_of_interest": ["mathematics", "science", "english"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["profile_complete"] is True
        assert data["age"] == 12
        assert data["highest_education_level"] == "middle-school"
        assert "mathematics" in data["subjects_of_interest"]

    # Cleanup
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_profile_age_validation_too_young(mock_user):
    """Test profile update with age below minimum (5)."""
    async def mock_auth_dep():
        return mock_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.put(
            "/profile",
            json={
                "age": 3,  # Too young
                "highest_education_level": "elementary",
                "subjects_of_interest": ["mathematics"],
            },
        )
        assert response.status_code == 422  # Validation error

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_profile_age_validation_too_old(mock_user):
    """Test profile update with age above maximum (120)."""
    async def mock_auth_dep():
        return mock_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.put(
            "/profile",
            json={
                "age": 150,  # Too old
                "highest_education_level": "graduate",
                "subjects_of_interest": ["philosophy"],
            },
        )
        assert response.status_code == 422  # Validation error

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_profile_invalid_education_level(mock_user):
    """Test profile update with invalid education level."""
    async def mock_auth_dep():
        return mock_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.put(
            "/profile",
            json={
                "age": 25,
                "highest_education_level": "invalid-level",
                "subjects_of_interest": ["mathematics"],
            },
        )
        assert response.status_code == 422  # Validation error

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_profile_no_subjects(mock_user):
    """Test profile update with no subjects (should fail)."""
    async def mock_auth_dep():
        return mock_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.put(
            "/profile",
            json={
                "age": 15,
                "highest_education_level": "high-school",
                "subjects_of_interest": [],  # Empty
            },
        )
        assert response.status_code == 422  # Validation error

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_profile_too_many_subjects(mock_user):
    """Test profile update with more than 15 subjects."""
    async def mock_auth_dep():
        return mock_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    # Create 16 subjects
    subjects = [f"subject{i}" for i in range(16)]

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.put(
            "/profile",
            json={
                "age": 15,
                "highest_education_level": "high-school",
                "subjects_of_interest": subjects,
            },
        )
        assert response.status_code == 422  # Validation error

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_profile_with_custom_other_subject(mock_user):
    """Test profile update with custom 'other' subject."""
    async def mock_auth_dep():
        return mock_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.put(
            "/profile",
            json={
                "age": 10,
                "highest_education_level": "elementary",
                "subjects_of_interest": ["mathematics", "music"],  # music as custom
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "music" in data["subjects_of_interest"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_profile_all_education_levels(mock_user):
    """Test that all education levels are valid."""
    async def mock_auth_dep():
        return mock_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    education_levels = [
        "elementary",
        "middle-school",
        "high-school",
        "college",
        "graduate",
        "other",
    ]

    async with AsyncClient(app=app, base_url="http://test") as ac:
        for level in education_levels:
            response = await ac.put(
                "/profile",
                json={
                    "age": 15,
                    "highest_education_level": level,
                    "subjects_of_interest": ["mathematics"],
                },
            )
            assert response.status_code == 200, f"Failed for level: {level}"
            data = response.json()
            assert data["highest_education_level"] == level

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_profile_multiple_subjects(mock_user):
    """Test profile update with multiple subjects."""
    async def mock_auth_dep():
        return mock_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    subjects = [
        "mathematics",
        "science",
        "english",
        "history",
        "computer-science",
        "physics",
    ]

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.put(
            "/profile",
            json={
                "age": 14,
                "highest_education_level": "middle-school",
                "subjects_of_interest": subjects,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["subjects_of_interest"]) == len(subjects)
        for subject in subjects:
            assert subject in data["subjects_of_interest"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_profile_returns_user_data(mock_completed_user):
    """Test GET /profile returns user's profile data."""
    async def mock_auth_dep():
        return mock_completed_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/profile")
        assert response.status_code == 200
        data = response.json()
        assert data["profile_complete"] is True
        assert data["age"] == 12
        assert data["highest_education_level"] == "middle-school"
        assert "mathematics" in data["subjects_of_interest"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_profile_sets_completed_flag(mock_user):
    """Test that updating profile sets profile_complete to True."""
    async def mock_auth_dep():
        return mock_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Update profile
        response = await ac.put(
            "/profile",
            json={
                "age": 8,
                "highest_education_level": "elementary",
                "subjects_of_interest": ["mathematics", "science"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["profile_complete"] is True  # Should be marked as complete

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_profile_edge_case_ages(mock_user):
    """Test profile update with edge case ages (5 and 120)."""
    async def mock_auth_dep():
        return mock_user

    app.dependency_overrides[clerk_auth_dependency] = mock_auth_dep

    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Test minimum age (5)
        response = await ac.put(
            "/profile",
            json={
                "age": 5,
                "highest_education_level": "elementary",
                "subjects_of_interest": ["mathematics"],
            },
        )
        assert response.status_code == 200

        # Test maximum age (120)
        response = await ac.put(
            "/profile",
            json={
                "age": 120,
                "highest_education_level": "graduate",
                "subjects_of_interest": ["philosophy"],
            },
        )
        assert response.status_code == 200

    app.dependency_overrides.clear()

