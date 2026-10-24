"""SQLAlchemy engine and session management.

Maps to Section 4.1 of the design: Data access layer bootstrap (Supabase Postgres).

Notes:
- The app uses an **async** SQLAlchemy engine (asyncpg).
- Alembic runs in **sync** mode via env.py by adapting the URL.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_settings = get_settings()

# Remove query parameters from URL and pass them as connect_args
# This fixes asyncpg type conversion issues
import urllib.parse
parsed_url = urllib.parse.urlparse(_settings.DATABASE_URL)
if parsed_url.query:
    # Rebuild URL without query parameters
    clean_url = urllib.parse.urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        '',  # params
        '',  # query - remove this
        ''   # fragment
    ))
    
    # Parse query parameters and convert to proper types for asyncpg
    query_params = dict(urllib.parse.parse_qsl(parsed_url.query))
    connect_args = {}
    
    # Convert string values to appropriate types
    if 'prepared_statement_cache_size' in query_params:
        connect_args['prepared_statement_cache_size'] = int(query_params['prepared_statement_cache_size'])
    if 'statement_cache_size' in query_params:
        connect_args['statement_cache_size'] = int(query_params['statement_cache_size'])
    
    # Add connection timeout for asyncpg (default 30 seconds)
    # This is the timeout for establishing the initial connection
    if 'timeout' not in connect_args:
        connect_args['timeout'] = 30
    
    # Add statement timeout (command_timeout) to prevent long-running queries
    # Increased to 120 seconds to handle slow INSERTs during migration/index creation
    # This prevents queries from hanging indefinitely
    if 'command_timeout' not in connect_args:
        connect_args['command_timeout'] = 120  # Increased from 60 to 120 seconds
    
    ENGINE: AsyncEngine = create_async_engine(
        clean_url,
        pool_pre_ping=True,
        future=True,
        pool_size=5,  # Number of connections to maintain
        max_overflow=10,  # Additional connections that can be created
        pool_timeout=30,  # Seconds to wait before giving up on getting a connection
        connect_args=connect_args,
    )
else:
    # Default connection args with timeout
    connect_args = {
        'timeout': 30,  # 30 second timeout for establishing asyncpg connections
        'command_timeout': 120,  # 120 second statement timeout (increased to handle slow operations)
    }
    
    ENGINE: AsyncEngine = create_async_engine(
        _settings.DATABASE_URL,
        pool_pre_ping=True,
        future=True,
        pool_size=5,  # Number of connections to maintain
        max_overflow=10,  # Additional connections that can be created
        pool_timeout=30,  # Seconds to wait before giving up on getting a connection
        connect_args=connect_args,
    )

SessionLocal = async_sessionmaker(
    ENGINE,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession for request contexts.

    This is a dependency intended for FastAPI. It yields a live
    AsyncSession instance (not a contextmanager) so that
    `Depends(get_session)` receives the session object.
    """
    session: AsyncSession = SessionLocal()
    try:
        yield session
    finally:
        await session.close()
