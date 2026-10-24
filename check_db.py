import asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings


async def main():
    settings = get_settings()
    url = settings.DATABASE_URL
    print("Trying:", url)
    engine = create_async_engine(url, future=True)
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            r = await conn.execute(text("SELECT 1"))
            print("SELECT 1 ->", r.scalar_one())
    except Exception as e:
        print("Connection failed:", type(e).__name__, e)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
