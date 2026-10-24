"""
Diagnostic script to check user role in database and via API.
"""
import asyncio
import httpx
from app.db.base import SessionLocal
from app.db.models import AppUser
from sqlalchemy import select

async def check_user_role():
    """Check the user's role in the database."""
    clerk_user_id = "user_337jFJOUtPIfqNbxYESdgIHhp8T"
    
    print("=" * 60)
    print("DIAGNOSTIC: User Role Check")
    print("=" * 60)
    
    # Check database
    async with SessionLocal() as session:
        result = await session.execute(
            select(AppUser.id, AppUser.clerk_user_id, AppUser.role, AppUser.full_name)
            .where(AppUser.clerk_user_id == clerk_user_id)
        )
        row = result.first()
        
        if row:
            print("\n✓ Database record found:")
            print(f"  ID: {row[0]}")
            print(f"  Clerk ID: {row[1]}")
            print(f"  Role: {row[2]}")
            print(f"  Name: {row[3]}")
            
            if row[2] == "admin":
                print("\n✓ User IS admin in database")
            else:
                print(f"\n✗ User is NOT admin (role={row[2]})")
        else:
            print("\n✗ User not found in database")
    
    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(check_user_role())
