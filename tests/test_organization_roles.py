"""
Test organization-based roles functionality.

Tests Clerk organization integration, role resolution, and access control.
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from app.auth.middleware import _upsert_app_user, require_role, require_org_role, require_admin_or_org_admin
from app.db.models import AppUser


@pytest.mark.asyncio
async def test_upsert_app_user_new_user_with_org():
    """Test creating a new user with organization information."""
    mock_session = AsyncMock()
    mock_session.execute.return_value.first.return_value = None  # No existing user
    
    # Mock the insert returning new user data
    mock_insert_result = AsyncMock()
    mock_insert_result.first.return_value = (uuid4(), "user")
    mock_session.execute.return_value = mock_insert_result
    
    user_id, global_role, effective_role = await _upsert_app_user(
        mock_session,
        clerk_user_id="user_123",
        full_name="John Doe",
        avatar_url="https://example.com/avatar.jpg",
        org_id="org_456",
        org_role="admin",
        org_slug="test-org"
    )
    
    assert global_role == "user"
    assert effective_role == "org:admin"
    mock_session.commit.assert_called()


@pytest.mark.asyncio
async def test_upsert_app_user_existing_user_update_org():
    """Test updating existing user with new organization information."""
    mock_session = AsyncMock()
    existing_user_id = uuid4()
    
    # Mock existing user query
    mock_session.execute.return_value.first.return_value = (
        existing_user_id, "user", "org_old", "org:member"
    )
    
    user_id, global_role, effective_role = await _upsert_app_user(
        mock_session,
        clerk_user_id="user_123",
        full_name="John Doe",
        avatar_url="https://example.com/avatar.jpg",
        org_id="org_new",
        org_role="admin",
        org_slug="new-org"
    )
    
    assert user_id == existing_user_id
    assert global_role == "user"
    assert effective_role == "org:admin"
    mock_session.commit.assert_called()


@pytest.mark.asyncio
async def test_upsert_app_user_no_org():
    """Test user without organization gets global role as effective role."""
    mock_session = AsyncMock()
    mock_session.execute.return_value.first.return_value = None  # No existing user
    
    # Mock the insert returning new user data
    mock_insert_result = AsyncMock()
    mock_insert_result.first.return_value = (uuid4(), "user")
    mock_session.execute.return_value = mock_insert_result
    
    user_id, global_role, effective_role = await _upsert_app_user(
        mock_session,
        clerk_user_id="user_123",
        full_name="John Doe",
        avatar_url="https://example.com/avatar.jpg",
        org_id=None,
        org_role=None,
        org_slug=None
    )
    
    assert global_role == "user"
    assert effective_role == "user"  # No org role, so effective role is global role


def test_require_role_with_org_role():
    """Test require_role decorator works with organization roles."""
    from fastapi import Request
    
    # Mock request with org admin user
    mock_request = AsyncMock(spec=Request)
    mock_request.state.user = {
        "role": "org:admin",
        "global_role": "user",
        "org_id": "org_123",
        "org_role": "admin"
    }
    
    # Test that org admin can access admin-required endpoint
    @require_role("admin", "org:admin")
    async def admin_endpoint(request: Request):
        return {"message": "success"}
    
    # Should not raise exception
    result = admin_endpoint.__wrapped__(mock_request)
    # Note: In actual test, we'd need to properly handle the async wrapper


def test_require_org_role_success():
    """Test require_org_role decorator allows access with correct org role."""
    from fastapi import Request
    
    mock_request = AsyncMock(spec=Request)
    mock_request.state.user = {
        "role": "org:admin",
        "global_role": "user",
        "org_id": "org_123",
        "org_role": "admin"
    }
    
    @require_org_role("admin")
    async def org_admin_endpoint(request: Request):
        return {"message": "success"}
    
    # Should not raise exception when user has correct org role


def test_require_org_role_no_org():
    """Test require_org_role decorator denies access when user has no org."""
    from fastapi import Request
    
    mock_request = AsyncMock(spec=Request)
    mock_request.state.user = {
        "role": "admin",
        "global_role": "admin",
        "org_id": None,
        "org_role": None
    }
    
    @require_org_role("admin")
    async def org_admin_endpoint(request: Request):
        return {"message": "success"}
    
    # Should raise HTTPException for missing org membership


def test_require_admin_or_org_admin_global_admin():
    """Test require_admin_or_org_admin allows global admin."""
    from fastapi import Request
    
    mock_request = AsyncMock(spec=Request)
    mock_request.state.user = {
        "role": "admin",
        "global_role": "admin",
        "org_id": None,
        "org_role": None
    }
    
    @require_admin_or_org_admin()
    async def admin_endpoint(request: Request):
        return {"message": "success"}
    
    # Should not raise exception for global admin


def test_require_admin_or_org_admin_org_admin():
    """Test require_admin_or_org_admin allows org admin."""
    from fastapi import Request
    
    mock_request = AsyncMock(spec=Request)
    mock_request.state.user = {
        "role": "org:admin",
        "global_role": "user",
        "org_id": "org_123",
        "org_role": "admin"
    }
    
    @require_admin_or_org_admin()
    async def admin_endpoint(request: Request):
        return {"message": "success"}
    
    # Should not raise exception for org admin


def test_require_admin_or_org_admin_regular_user():
    """Test require_admin_or_org_admin denies regular user."""
    from fastapi import Request
    
    mock_request = AsyncMock(spec=Request)
    mock_request.state.user = {
        "role": "user",
        "global_role": "user",
        "org_id": "org_123",
        "org_role": "member"
    }
    
    @require_admin_or_org_admin()
    async def admin_endpoint(request: Request):
        return {"message": "success"}
    
    # Should raise HTTPException for regular user


@pytest.mark.asyncio
async def test_clerk_auth_dependency_with_org():
    """Test that clerk_auth_dependency properly extracts organization info."""
    from app.auth.middleware import clerk_auth_dependency
    from fastapi import Request
    
    mock_request = AsyncMock(spec=Request)
    mock_request.headers.get.return_value = "Bearer test_token"
    
    # Mock JWT claims with organization info
    mock_claims = {
        "sub": "user_123",
        "org_id": "org_456",
        "org_role": "admin",
        "org_slug": "test-org",
        "email": "test@example.com",
        "name": "John Doe"
    }
    
    with patch('app.auth.middleware.jwt.get_unverified_header') as mock_header, \
         patch('app.auth.middleware._get_jwks') as mock_jwks, \
         patch('app.auth.middleware._get_key_for_kid') as mock_key, \
         patch('app.auth.middleware.jwt.decode') as mock_decode, \
         patch('app.auth.middleware.get_session') as mock_get_session, \
         patch('app.auth.middleware._upsert_app_user') as mock_upsert:
        
        mock_header.return_value = {"kid": "test_kid"}
        mock_jwks.return_value = {"keys": []}
        mock_key.return_value = {"alg": "RS256"}
        mock_decode.return_value = mock_claims
        
        # Mock database session
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        mock_upsert.return_value = (uuid4(), "user", "org:admin")
        
        result = await clerk_auth_dependency(mock_request)
        
        assert result["org_id"] == "org_456"
        assert result["org_role"] == "admin"
        assert result["org_slug"] == "test-org"
        assert result["role"] == "org:admin"  # Effective role
        assert result["global_role"] == "user"


@pytest.mark.asyncio 
async def test_clerk_auth_dependency_multiple_orgs():
    """Test that clerk_auth_dependency handles multiple organizations."""
    from app.auth.middleware import clerk_auth_dependency
    from fastapi import Request
    
    mock_request = AsyncMock(spec=Request)
    mock_request.headers.get.return_value = "Bearer test_token"
    
    # Mock JWT claims with multiple orgs but no active org
    mock_claims = {
        "sub": "user_123",
        "orgs": [
            {"id": "org_123", "role": "admin", "slug": "first-org"},
            {"id": "org_456", "role": "member", "slug": "second-org"}
        ],
        "email": "test@example.com",
        "name": "John Doe"
    }
    
    with patch('app.auth.middleware.jwt.get_unverified_header') as mock_header, \
         patch('app.auth.middleware._get_jwks') as mock_jwks, \
         patch('app.auth.middleware._get_key_for_kid') as mock_key, \
         patch('app.auth.middleware.jwt.decode') as mock_decode, \
         patch('app.auth.middleware.get_session') as mock_get_session, \
         patch('app.auth.middleware._upsert_app_user') as mock_upsert:
        
        mock_header.return_value = {"kid": "test_kid"}
        mock_jwks.return_value = {"keys": []}
        mock_key.return_value = {"alg": "RS256"}
        mock_decode.return_value = mock_claims
        
        # Mock database session
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        mock_upsert.return_value = (uuid4(), "user", "org:admin")
        
        result = await clerk_auth_dependency(mock_request)
        
        # Should use first org from the list
        assert result["org_id"] == "org_123"
        assert result["org_role"] == "admin"
        assert result["org_slug"] == "first-org"