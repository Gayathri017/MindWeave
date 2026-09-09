"""Reads back a user's saved items -- the list view the frontend's left panel needs."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Concept, ConceptMention, Item
from app.models.schemas import ItemWithConcepts

_DEFAULT_LIMIT = 100


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
        )
        for item in items
    ]