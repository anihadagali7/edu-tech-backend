"""Add organization columns to existing app_users table."""
import asyncio
from app.config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def add_org_columns():
    """Add organization columns that our code needs."""
    engine = create_async_engine(get_settings().DATABASE_URL)
    
    try:
        async with engine.begin() as conn:
            print("Adding organization columns to app_users...")
            
            # Add org columns if they don't exist
            await conn.execute(text("""
                ALTER TABLE app_users 
                ADD COLUMN IF NOT EXISTS active_org_id TEXT,
                ADD COLUMN IF NOT EXISTS active_org_slug TEXT
            """))
            
            # Add index
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_app_users_active_org_id 
                ON app_users(active_org_id)
            """))
            
            print("✓ Organization columns added successfully!")
            
    except Exception as e:
        print(f'❌ Error: {e}')
        import traceback
        traceback.print_exc()
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(add_org_columns())
