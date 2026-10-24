"""Check DB schema vs ORM models.

Usage:
  Activate venv, then:
    python scripts/check_db_schema.py

This script reads DATABASE_URL from `app.config.get_settings()` and connects
to the database, then compares expected table columns from `app.db.models`
with actual columns in information_schema. It prints missing and extra
columns per table.
"""
from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import asyncpg

from app.config import get_settings
import app.db.models as models


async def get_db_columns(conn: asyncpg.Connection, table: str, schema: str = "public") -> set[str]:
    sql = """
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = $1 AND table_name = $2
    """
    rows = await conn.fetch(sql, schema, table)
    return {r["column_name"] for r in rows}


def orm_table_columns() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    # Inspect declarative base classes in models module
    for name in dir(models):
        obj = getattr(models, name)
        try:
            table = getattr(obj, "__tablename__")
        except Exception:
            continue
        cols = {c.name for c in obj.__table__.columns}
        out[table] = cols
    return out


async def main() -> None:
    settings = get_settings()
    db_url = settings.DATABASE_URL
    if db_url.startswith("postgresql+asyncpg://"):
        # adapt to asyncpg connect URL (drop +asyncpg)
        connect_url = db_url.replace("+asyncpg", "")
    else:
        connect_url = db_url

    # asyncpg requires 'postgresql://' or 'postgres://' scheme
    parsed = urlparse(connect_url)
    if parsed.scheme not in ("postgresql", "postgres"):
        print("Unsupported DB URL scheme:", parsed.scheme)
        return

    print("Connecting to:", connect_url)
    conn = await asyncpg.connect(connect_url)
    try:
        orm = orm_table_columns()
        all_ok = True
        for table, expected_cols in sorted(orm.items()):
            actual = await get_db_columns(conn, table)
            missing = expected_cols - actual
            extra = actual - expected_cols
            if missing or extra:
                all_ok = False
                print(f"\nTable: {table}")
                if missing:
                    print(f"  Missing columns ({len(missing)}): {sorted(missing)}")
                if extra:
                    print(f"  Extra columns ({len(extra)}): {sorted(extra)}")
            else:
                print(f"Table {table}: OK")

        if all_ok:
            print("\nAll ORM tables match DB columns (columns present). Good.")
        else:
            print("\nSchema differences found. Consider running alembic upgrade head or applying corrective migrations.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
