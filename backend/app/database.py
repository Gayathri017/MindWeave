"""Async database engine and per-request, RLS-scoped session management.

Row Level Security (RLS) in Postgres only applies to roles that don't have
the BYPASSRLS attribute, and Mindweave's policies check `auth.uid()`, which
Supabase defines as reading the Postgres session setting
`request.jwt.claim.sub`. PostgREST sets that automatically for you; since
this backend talks to Postgres directly instead, we set it ourselves, for
the lifetime of one transaction, right after verifying the caller's JWT --
and we drop into Supabase's built-in `authenticated` role (which does not
bypass RLS) to run the query. That means RLS is genuinely enforced: a bug
in application code that forgot to filter a query by user_id still cannot
leak another user's rows, because the database itself refuses.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import get_current_user_id
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
    echo=not settings.is_production,
)

_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def _user_scoped_session(user_id: str) -> AsyncGenerator[AsyncSession, None]:
    # SET LOCAL doesn't support bind parameters, so instead of trusting the
    # raw string we validate it's a well-formed UUID first -- that's what
    # makes the interpolation below safe, not an oversight.
    safe_user_id = str(uuid.UUID(user_id))

    async with _session_factory() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL ROLE authenticated"))
            await session.execute(text(f"SET LOCAL request.jwt.claim.sub = '{safe_user_id}'"))
            yield session


async def get_db_for_request(
    user_id: str = Depends(get_current_user_id),
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: a request-scoped, RLS-enforced database session."""
    async with _user_scoped_session(user_id) as session:
        yield session
