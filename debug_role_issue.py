"""Debug script to check current role configuration."""
import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.db.models import AppUser

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not found in environment")
    exit(1)

async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Get the user with your Clerk ID
        clerk_user_id = "user_337jFJOUtPIfqNbxYESdgIHhp8T"
        
        result = await session.execute(
            select(AppUser).where(AppUser.clerk_user_id == clerk_user_id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            print("=" * 60)
            print("✅ USER FOUND IN DATABASE")
            print("=" * 60)
            print(f"  ID: {user.id}")
            print(f"  Clerk ID: {user.clerk_user_id}")
            print(f"  Name: {user.full_name}")
            print(f"  Role: {user.role}")
            print(f"  Role Type: {type(user.role)}")
            print("=" * 60)
            
            # Check what it should be
            print("\n🔍 ROLE STATUS CHECK:")
            if user.role == "TEACHER":
                print("  ✅ Role is TEACHER (correct for admin)")
            elif user.role == "admin":
                print("  ⚠️  Role is 'admin' (old value - needs update)")
                print("  💡 You need to update Clerk to use 'TEACHER' instead")
            elif user.role == "STUDENT":
                print("  ⚠️  Role is STUDENT (regular user)")
            else:
                print(f"  ❌ Role is '{user.role}' (unexpected value)")
            
            print("\n📋 WHAT FRONTEND SHOULD CHECK:")
            print(f"  Frontend should check: user.role === 'TEACHER'")
            print(f"  Current value would return: user.role === '{user.role}'")
            
        else:
            print(f"❌ User not found with Clerk ID: {clerk_user_id}")

if __name__ == "__main__":
    asyncio.run(main())
