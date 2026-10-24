"""Update database role from TEACHER back to admin."""
import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.db.models import AppUser

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        clerk_user_id = "user_337jFJOUtPIfqNbxYESdgIHhp8T"
        
        # Update the role back to admin
        await session.execute(
            update(AppUser)
            .where(AppUser.clerk_user_id == clerk_user_id)
            .values(role="admin")
        )
        await session.commit()
        
        print("=" * 60)
        print("✅ DATABASE UPDATED")
        print("=" * 60)
        print(f"  User: {clerk_user_id}")
        print(f"  Role updated: TEACHER → admin")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
