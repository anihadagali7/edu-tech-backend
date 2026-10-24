"""Check current database migration version."""
import asyncio
from app.config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def check():
    engine = create_async_engine(get_settings().DATABASE_URL)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text('SELECT version_num FROM alembic_version'))
            row = result.fetchone()
            if row:
                version = row[0]
                print(f'Current DB migration version: {version}')
                return version
            else:
                print('No migration version found in database')
                return None
    except Exception as e:
        print(f'Error checking version: {e}')
        return None
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check())
