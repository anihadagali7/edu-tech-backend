"""Revert migration version back to colleague's version."""
import asyncio
from app.config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def revert_migration():
    """Revert back to the version that was in the database."""
    engine = create_async_engine(get_settings().DATABASE_URL)
    
    try:
        async with engine.begin() as conn:
            # Revert to colleague's version
            await conn.execute(text(
                "UPDATE alembic_version SET version_num = '0008_add_profile_fields'"
            ))
            
            print(f'✓ Reverted to: 0008_add_profile_fields')
    except Exception as e:
        print(f'❌ Error: {e}')
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(revert_migration())
