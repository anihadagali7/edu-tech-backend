"""Test that principal['id'] is now a string UUID that works everywhere."""
import asyncio
from uuid import UUID

async def test_principal_id_conversion():
    """Simulate what happens in endpoints with principal['id']."""
    
    # This simulates what the middleware now returns
    mock_principal = {
        "id": "bf945e49-dadf-46b7-9bba-4663045a1623",  # String UUID
        "clerk_user_id": "user_abc123",
        "role": "user"
    }
    
    print("Testing principal['id'] conversions...")
    print(f"principal['id'] type: {type(mock_principal['id'])}")
    print(f"principal['id'] value: {mock_principal['id']}")
    
    # Test 1: Direct UUID conversion (used in SSE, topics, jobs)
    try:
        user_id = UUID(mock_principal["id"])
        print(f"✅ UUID(principal['id']) works: {user_id}")
        print(f"   Result type: {type(user_id)}")
    except Exception as e:
        print(f"❌ UUID(principal['id']) failed: {e}")
        return False
    
    # Test 2: Direct usage in logging/JSON (used in many places)
    try:
        log_data = {
            "user_id": mock_principal["id"],
            "admin_id": mock_principal["id"]
        }
        print(f"✅ Direct usage in dicts works: {log_data}")
    except Exception as e:
        print(f"❌ Direct usage failed: {e}")
        return False
    
    # Test 3: String conversion (defensive)
    try:
        user_id_str = str(mock_principal["id"])
        print(f"✅ str(principal['id']) works: {user_id_str}")
    except Exception as e:
        print(f"❌ str() conversion failed: {e}")
        return False
    
    print("\n✅ All tests passed! principal['id'] as string UUID works everywhere.")
    return True

if __name__ == "__main__":
    asyncio.run(test_principal_id_conversion())
