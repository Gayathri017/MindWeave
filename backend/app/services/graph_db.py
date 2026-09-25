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


def normalize_name(name: str) -> str:
    """Same normalization the Postgres concept graph uses -- so "GraphRAG"
    and "graphrag" from two different extractions collapse into one node
    instead of fragmenting the graph.
    """
    return name.strip().lower()


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


_UPSERT_RELATION_QUERY = """
MERGE (s:Concept {user_id: $user_id, name: $subject})
MERGE (o:Concept {user_id: $user_id, name: $object})
MERGE (s)-[r:RELATES {type: $relation, user_id: $user_id}]->(o)
ON CREATE SET r.weight = 1, r.item_ids = [$item_id]
ON MATCH SET
    r.weight = r.weight + 1,
    r.item_ids = CASE WHEN $item_id IN r.item_ids THEN r.item_ids ELSE r.item_ids + $item_id END
"""


async def store_relations_for_item(
    user_id: str, item_id: str, relations: list[tuple[str, str, str]]
) -> None:
    """Write (subject, relation, object) triples extracted from one item
    into the graph. Best-effort by design -- callers should wrap this in
    the same try/except-and-log pattern already used for the Postgres
    concept graph in extraction.py, so a GraphRAG hiccup never fails a
    save that otherwise succeeded.
    """
    if not relations:
        return
    async with get_graph_session() as session:
        if session is None:
            return
        for subject, relation, obj in relations:
            await session.run(
                _UPSERT_RELATION_QUERY,
                user_id=user_id,
                item_id=item_id,
                subject=normalize_name(subject),
                relation=normalize_name(relation).replace(" ", "_"),
                object=normalize_name(obj),
            )


_NEIGHBORS_QUERY = """
MATCH (c:Concept {user_id: $user_id})
WHERE c.name IN $concept_names
MATCH (c)-[r:RELATES {user_id: $user_id}]-(neighbor:Concept {user_id: $user_id})
RETURN DISTINCT c.name AS concept, r.type AS relation, neighbor.name AS neighbor,
       startNode(r).name AS subject, endNode(r).name AS object
LIMIT $limit
"""


async def get_related_concepts(
    user_id: str, concept_names: list[str], limit: int = 25
) -> list[dict[str, str]]:
    """One-hop neighbors (in either direction) of the given concepts, with
    the relation type and its original subject/object direction -- this is
    the actual GraphRAG step: extra context pulled from the graph to hand
    the chat model alongside the vector-search excerpts.

    Returns [] if GraphRAG isn't configured or none of the concepts exist
    yet in the graph -- always a safe, empty fallback, never an error.
    """
    if not concept_names:
        return []
    async with get_graph_session() as session:
        if session is None:
            return []
        normalized = [normalize_name(name) for name in concept_names]
        result = await session.run(
            _NEIGHBORS_QUERY, user_id=user_id, concept_names=normalized, limit=limit
        )
        records = await result.data()
        return [
            {"subject": r["subject"], "relation": r["relation"], "object": r["object"]}
            for r in records
        ]


_RELATIONS_FOR_ITEMS_QUERY = """
MATCH (s:Concept {user_id: $user_id})-[r:RELATES {user_id: $user_id}]->(o:Concept {user_id: $user_id})
WHERE any(id IN r.item_ids WHERE id IN $item_ids)
RETURN DISTINCT s.name AS subject, r.type AS relation, o.name AS object
LIMIT $limit
"""


async def get_relations_for_items(
    user_id: str, item_ids: list[str], limit: int = 25
) -> list[dict[str, str]]:
    """Relations extracted directly from the given items (by item ID, not
    by matching concept names against the separate flat-concept
    extraction -- that extraction runs as an independent Gemini call with
    its own vocabulary, e.g. "hotpotqa dataset" there vs "hotpotqa" here,
    so joining on name silently misses everything). Item ID is the only
    reliable link between a vector-search match and its graph relations.

    Returns [] if GraphRAG isn't configured or the item has no relations
    (most items won't -- this is a papers/reports-only extraction).
    """
    if not item_ids:
        return []
    async with get_graph_session() as session:
        if session is None:
            return []
        result = await session.run(
            _RELATIONS_FOR_ITEMS_QUERY, user_id=user_id, item_ids=item_ids, limit=limit
        )
        records = await result.data()
        return [{"subject": r["subject"], "relation": r["relation"], "object": r["object"]} for r in records]
