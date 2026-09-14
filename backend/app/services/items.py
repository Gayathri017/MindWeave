"""Reads back a user's saved items -- the list view the frontend's left panel needs."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Concept, ConceptMention, Item
from app.models.schemas import ItemWithConcepts

_DEFAULT_LIMIT = 100
_PREVIEW_LENGTH = 100


def _make_preview(raw_text: str, limit: int = _PREVIEW_LENGTH) -> str:
    """First ~100 characters, cut at a word boundary rather than mid-word."""
    stripped = raw_text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rsplit(" ", 1)[0] + "\u2026"


async def list_items(session: AsyncSession, user_id: str, limit: int = _DEFAULT_LIMIT) -> list[ItemWithConcepts]:
    """Most recent items first, each with the concept names it's tagged with.

    Two queries rather than one big join-and-group: simpler to read, and
    avoids repeating each item's columns once per concept it has.
    """
    items = (
        (
            await session.execute(
                select(Item).where(Item.user_id == user_id).order_by(Item.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not items:
        return []

    item_ids = [item.id for item in items]
    mention_rows = (
        await session.execute(
            select(ConceptMention.item_id, Concept.name)
            .join(Concept, Concept.id == ConceptMention.concept_id)
            .where(ConceptMention.item_id.in_(item_ids))
        )
    ).all()

    concepts_by_item: dict[uuid.UUID, list[str]] = {}
    for item_id, name in mention_rows:
        concepts_by_item.setdefault(item_id, []).append(name)

    return [
        ItemWithConcepts(
            id=item.id,
            source_type=item.source_type,
            source_url=item.source_url,
            title=item.title,
            created_at=item.created_at,
            concepts=concepts_by_item.get(item.id, []),
            preview=_make_preview(item.raw_text),
            extracted_data=item.extracted_data,
        )
        for item in items
    ]


async def delete_item(session: AsyncSession, user_id: str, item_id: uuid.UUID) -> bool:
    """Delete an item, then clean up any concepts left with no items behind them.

    Deleting the item cascades (via the foreign keys in db/schema.sql) to
    its chunks and concept_mentions automatically. But concepts themselves
    are independent of any one item -- after that cascade, a concept that
    only ever appeared in this item now has zero mentions left. Left alone,
    it would sit in the graph forever as a node pointing at nothing. This
    finds and removes exactly those now-orphaned concepts (which in turn
    cascades to any concept_links involving them).

    Returns True if an item was actually deleted, False if nothing matched
    (already gone, or never belonged to this user).
    """
    result = await session.execute(delete(Item).where(Item.id == item_id, Item.user_id == user_id))
    if result.rowcount == 0:
        return False

    orphaned = await session.execute(
        select(Concept.id)
        .where(Concept.user_id == user_id)
        .where(~Concept.id.in_(select(ConceptMention.concept_id)))
    )
    orphaned_ids = [row[0] for row in orphaned.all()]
    if orphaned_ids:
        await session.execute(delete(Concept).where(Concept.id.in_(orphaned_ids)))

    return True