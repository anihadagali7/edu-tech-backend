"""
Quick test to verify admin role checking is working.
Run this after restarting the server.
"""
import asyncio
from app.auth.middleware import clerk_auth_dependency, require_role
from fastapi import Request, HTTPException
from unittest.mock import Mock

async def test_require_role():
    """Test that require_role dependency properly checks roles."""
    
    # Create a mock request with admin user
    mock_request = Mock(spec=Request)
    mock_request.state = Mock()
    mock_request.state.user = {
        "id": "test-user-id",
        "clerk_user_id": "clerk_123",
        "role": "admin",
        "profile_complete": False,
    }
    
    # Test admin role check (should pass)
    admin_dependency = require_role("admin")
    try:
        result = await admin_dependency(mock_request)
        print("✓ Admin role check PASSED")
        print(f"  Returned user: {result}")
    except HTTPException as e:
        print(f"✗ Admin role check FAILED: {e.detail}")
        return False
    
    # Test with wrong role (should fail)
    mock_request.state.user["role"] = "user"
    try:
        result = await admin_dependency(mock_request)
        print("✗ Non-admin should have been rejected but wasn't!")
        return False
    except HTTPException as e:
        print(f"✓ Non-admin correctly rejected: {e.detail}")
    
    # Test with no user (should fail)
    mock_request.state.user = None
    try:
        result = await admin_dependency(mock_request)
        print("✗ No user should have been rejected but wasn't!")
        return False
    except HTTPException as e:
        print(f"✓ No user correctly rejected: {e.detail}")
    
    print("\n✓ All tests passed! Admin role checking is working correctly.")
    return True

if __name__ == "__main__":
    asyncio.run(test_require_role())
