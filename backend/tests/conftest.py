"""Shared fixtures for integration tests that need a real database.

Folders, item filing, and chat persistence are genuine SQL logic (joins,
cascades, ownership checks) -- exactly the kind of thing that mocking a
session would let slip through untested. Consistent with this project's
existing rule (see test_chunking.py) of preferring a real database over
mocks, these fixtures point at a real, disposable Postgres+pgvector
instance rather than faking the session.

That instance is NOT the app's configured DATABASE_URL (production/dev
Supabase) -- it's a separate, local, throwaway container, so these tests
can never touch real data. Spin one up with:

    docker run -d --name mindweave-test-db -e POSTGRES_PASSWORD=test \\
        -p 55432:5432 pgvector/pgvector:pg16

Then apply db/schema.sql to it, plus a minimal `auth` schema stub for the
foreign keys schema.sql expects Supabase to provide (see
backend/README.md for the full one-time setup). Tests in this file
automatically skip -- rather than fail -- if that database isn't
reachable, so `pytest` stays green on a machine that never set this up.
"""

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:test@localhost:55432/postgres"
)


class _Availability:
    """A plain (non-async, session-scoped) cache of whether the test
    database answered -- so only the first test pays the connection-probe
    cost; every test after it either skips instantly or connects for
    real, instead of every single test re-running its own 3-second-timeout
    probe (which is correct but adds up to over a minute across the suite).
    """

    checked = False
    available = False


@pytest.fixture(scope="session")
def _db_availability():
    return _Availability()


@pytest_asyncio.fixture
async def db_engine(_db_availability):
    # Function-scoped, not session-scoped: pytest-asyncio hands each test
    # function its own event loop by default, and asyncpg's connections
    # are bound to the loop that created them -- reusing one engine (and
    # its pooled connections) across tests each running on a different
    # loop raises "another operation is in progress". A fresh engine per
    # test costs a little time but sidesteps that entirely.
    if _db_availability.checked and not _db_availability.available:
        pytest.skip(f"Test database not reachable at {TEST_DATABASE_URL} -- see conftest.py docstring to start one.")

    # A short connect timeout matters on the first probe: without one, a
    # database that's down in a way the OS doesn't immediately refuse
    # (rather than a normal "connection refused") can hang indefinitely --
    # turning "skip this test" into "pytest never finishes."
    engine = create_async_engine(TEST_DATABASE_URL, connect_args={"timeout": 3})
    if not _db_availability.checked:
        try:
            async with engine.connect():
                pass
            _db_availability.available = True
        except Exception:
            _db_availability.checked = True
            await engine.dispose()
            pytest.skip(
                f"Test database not reachable at {TEST_DATABASE_URL} -- see conftest.py docstring to start one."
            )
        _db_availability.checked = True

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session


async def _make_user(session: AsyncSession) -> uuid.UUID:
    """A real row in the auth.users stub -- every user-owned table's
    foreign key points there, and deleting it cascades away everything
    that test created, so tests don't need their own manual cleanup.
    """
    user_id = uuid.uuid4()
    await session.execute(text("insert into auth.users (id) values (:id)"), {"id": str(user_id)})
    await session.commit()
    return user_id


async def _delete_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(text("delete from auth.users where id = :id"), {"id": str(user_id)})
    await session.commit()


@pytest_asyncio.fixture
async def user_id(db_session):
    uid = await _make_user(db_session)
    yield uid
    await _delete_user(db_session, uid)


@pytest_asyncio.fixture
async def other_user_id(db_session):
    """A second, independent user -- for tests that check one user's
    folders/items are invisible to (and can't be targeted by) another.
    """
    uid = await _make_user(db_session)
    yield uid
    await _delete_user(db_session, uid)
