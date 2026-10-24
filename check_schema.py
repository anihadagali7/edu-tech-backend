"""Check actual app_users table schema in database."""
import asyncio
from app.config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def check_schema():
    """Check what columns exist in app_users table."""
    engine = create_async_engine(get_settings().DATABASE_URL)
    
    try:
        async with engine.connect() as conn:
            # Get column info from app_users table
            result = await conn.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'app_users'
                ORDER BY ordinal_position
            """))
            
            print("app_users table columns:")
            print("-" * 60)
            for row in result:
                print(f"  {row[0]:<30} {row[1]:<20} nullable={row[2]}")
    except Exception as e:
        print(f'❌ Error: {e}')
        import traceback
        traceback.print_exc()
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_schema())
