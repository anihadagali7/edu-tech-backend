#!/usr/bin/env python3
from __future__ import annotations
import os
import asyncio
import httpx
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import insert, update, select
from app.db.models import AppUser

CLERK_API_BASE = os.getenv("CLERK_API_BASE", "https://api.clerk.com")
CLERK_API_KEY = os.getenv("CLERK_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL")

async def main():
    engine = create_async_engine(DATABASE_URL, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    headers = {"Authorization": f"Bearer {CLERK_API_KEY}"}
    async with httpx.AsyncClient(timeout=10, headers=headers) as client, Session() as session:
        url = f"{CLERK_API_BASE}/v1/users?limit=100"
        while url:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            for u in data.get("data", []):
                clerk_user_id = u["id"]
                full_name = u.get("full_name")
                image_url = u.get("image_url")
                exists = (await session.execute(select(AppUser.id).where(AppUser.clerk_user_id == clerk_user_id))).first()
                if exists:
                    await session.execute(update(AppUser).where(AppUser.clerk_user_id == clerk_user_id).values(full_name=full_name, avatar_url=image_url))
                else:
                    await session.execute(insert(AppUser).values(clerk_user_id=clerk_user_id, full_name=full_name, avatar_url=image_url, role="user"))
            await session.commit()
            url = data.get("next_url")

if __name__ == "__main__":
    asyncio.run(main())