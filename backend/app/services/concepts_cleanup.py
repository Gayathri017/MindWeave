"""Shared cleanup for concepts left with no items behind them.

Split out from items.py/folders.py so both can use it without importing
each other -- an item delete and a folder delete (which bulk-deletes all
its items) both need this same sweep afterward.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Concept, ConceptMention


async def cleanup_orphaned_concepts(session: AsyncSession, user_id: str) -> None:
    """Remove any concept with zero mentions left.

    Concepts are independent of any one item -- after an item (or every
    item in a deleted folder) cascades away its mentions, a concept that
    only ever appeared there now points at nothing. Left alone it would
    sit in the graph forever; this sweeps those up (cascading to any
    concept_links involving them).
    """
    orphaned = await session.execute(
        select(Concept.id)
        .where(Concept.user_id == user_id)
        .where(~Concept.id.in_(select(ConceptMention.concept_id)))
    )
    orphaned_ids = [row[0] for row in orphaned.all()]
    if orphaned_ids:
        await session.execute(delete(Concept).where(Concept.id.in_(orphaned_ids)))
