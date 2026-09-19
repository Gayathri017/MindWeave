"""Reads back a user's saved items -- the list view the frontend's left panel needs."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Concept, ConceptMention, Item
from app.models.schemas import ItemWithConcepts
from app.services.concepts_cleanup import cleanup_orphaned_concepts
from app.services.folders import validate_folder_ownership

_DEFAULT_LIMIT = 100
_PREVIEW_LENGTH = 100


def _make_preview(raw_text: str, limit: int = _PREVIEW_LENGTH) -> str:
    """First ~100 characters, cut at a word boundary rather than mid-word."""
    stripped = raw_text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rsplit(" ", 1)[0] + "…"


async def list_items(
    session: AsyncSession, user_id: str, folder_id: uuid.UUID | None = None, limit: int = _DEFAULT_LIMIT
) -> list[ItemWithConcepts]:
    """Most recent items first, each with the concept names it's tagged with.

    Two queries rather than one big join-and-group: simpler to read, and
    avoids repeating each item's columns once per concept it has.
    """
    query = select(Item).where(Item.user_id == user_id)
    if folder_id is not None:
        query = query.where(Item.folder_id == folder_id)

    items = (await session.execute(query.order_by(Item.created_at.desc()).limit(limit))).scalars().all()
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
            folder_id=item.folder_id,
            created_at=item.created_at,
            concepts=concepts_by_item.get(item.id, []),
            preview=_make_preview(item.raw_text),
            extracted_data=item.extracted_data,
        )
        for item in items
    ]


async def get_item(session: AsyncSession, user_id: str, item_id: uuid.UUID) -> Item | None:
    return (
        await session.execute(select(Item).where(Item.id == item_id, Item.user_id == user_id))
    ).scalar_one_or_none()


async def delete_item(session: AsyncSession, user_id: str, item_id: uuid.UUID) -> bool:
    """Delete an item, then clean up any concepts left with no items behind them.

    Deleting the item cascades (via the foreign keys in db/schema.sql) to
    its chunks and concept_mentions automatically.

    Returns True if an item was actually deleted, False if nothing matched
    (already gone, or never belonged to this user).
    """
    result = await session.execute(delete(Item).where(Item.id == item_id, Item.user_id == user_id))
    if result.rowcount == 0:
        return False

    await cleanup_orphaned_concepts(session, user_id)
    return True


async def update_item_folder(
    session: AsyncSession, user_id: str, item_id: uuid.UUID, folder_id: uuid.UUID | None
) -> Item | None:
    """Move an item into a folder, or back to the main list if folder_id is None.

    Raises FolderNotFound if folder_id doesn't exist or isn't owned by this
    user -- lets the router turn that into a 404 rather than silently
    filing the item into a folder it can never actually see again.
    """
    item = (
        await session.execute(select(Item).where(Item.id == item_id, Item.user_id == user_id))
    ).scalar_one_or_none()
    if item is None:
        return None

    if folder_id is not None:
        await validate_folder_ownership(session, user_id, folder_id)

    item.folder_id = folder_id
    await session.flush()
    return item
