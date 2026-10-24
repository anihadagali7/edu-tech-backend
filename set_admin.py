"""
Quick script to set a user as admin in the database.
Run this to bypass the Clerk JWT template issue.
"""
import asyncio
from app.db.base import SessionLocal
from app.db.models import AppUser
from sqlalchemy import update

async def set_admin_role():
    """Set user as admin directly in database."""
    clerk_user_id = "user_337jFJOUtPIfqNbxYESdgIHhp8T"
    
    async with SessionLocal() as session:
        result = await session.execute(
            update(AppUser)
            .where(AppUser.clerk_user_id == clerk_user_id)
            .values(role="admin")
            .returning(AppUser.id, AppUser.clerk_user_id, AppUser.role, AppUser.full_name)
        )
        row = result.first()
        await session.commit()
        
        if row:
            print(f"✓ Successfully set user as admin:")
            print(f"  ID: {row[0]}")
            print(f"  Clerk ID: {row[1]}")
            print(f"  Role: {row[2]}")
            print(f"  Name: {row[3]}")
        else:
            print("✗ User not found in database")

if __name__ == "__main__":
    asyncio.run(set_admin_role())
