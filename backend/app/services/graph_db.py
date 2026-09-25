"""Async Neo4j driver for the GraphRAG concept graph.

Unlike Postgres, Neo4j has no equivalent of Supabase's Row Level Security
-- there's no database-enforced backstop here. Every node and relationship
this module writes carries a `user_id` property, and every query filters
on it explicitly. That means, unlike `app/database.py`, a bug that forgot
the filter WOULD leak across users -- so any new query added to this file
needs a `user_id` parameter and a `{user_id: $user_id}` (or equivalent
WHERE) clause, no exceptions. Treat this the same way you'd treat a raw
SQL query with no RLS to catch a mistake.

Entirely optional: if Neo4j isn't configured (see `Settings.graph_db_enabled`),
every function here is a no-op. GraphRAG is an enhancement on top of the
existing vector-RAG pipeline, never a dependency it needs to function.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

_driver: AsyncDriver | None = None
_truststore_injected = False


def _ensure_os_trust_store() -> None:
    """AuraDB's TLS endpoint doesn't send its full certificate chain, only
    the leaf cert. Windows (and most OSes) silently repair this by
    fetching the missing intermediate via the cert's Authority Information
    Access extension; Python's default certifi-based verification doesn't
    do that AIA fetch, so it fails a chain it has no real reason to
    distrust. `truststore` swaps in the OS's own verifier, which does the
    same repair Windows already does natively. Injected lazily, once, and
    only when GraphRAG is actually used -- this changes global `ssl`
    behavior for the whole process, so it shouldn't fire for a deployment
    that never touches Neo4j.
    """
    global _truststore_injected
    if _truststore_injected:
        return
    import truststore

    truststore.inject_into_ssl()
    _truststore_injected = True


def _get_driver() -> AsyncDriver | None:
    """Lazily create the driver on first use, not at import time -- so a
    deployment without Neo4j configured never pays for a connection
    attempt it doesn't need.
    """
    global _driver
    if not settings.graph_db_enabled:
        return None
    if _driver is None:
        _ensure_os_trust_store()
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )
    return _driver


@asynccontextmanager
async def get_graph_session() -> AsyncGenerator[AsyncSession | None, None]:
    """Yields a Neo4j session, or None if GraphRAG isn't configured --
    callers are expected to check for None and skip gracefully, the same
    way the rest of the app treats a missing TAVILY_API_KEY as "feature
    off", not an error.
    """
    driver = _get_driver()
    if driver is None:
        yield None
        return
    async with driver.session() as session:
        yield session


async def close_driver() -> None:
    """Call on app shutdown so the connection pool closes cleanly."""
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
