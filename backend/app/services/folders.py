"""Folder CRUD -- a folder is a true container (like a filesystem folder),
not a tag: each item belongs to at most one, and deleting a folder deletes
everything filed in it.
"""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Folder, Item
from app.models.schemas import FolderSummary
from app.services.concepts_cleanup import cleanup_orphaned_concepts


class FolderNotFound(Exception):
    """Raised when a target folder_id doesn't exist or isn't owned by this user."""


async def validate_folder_ownership(session: AsyncSession, user_id: str, folder_id: uuid.UUID) -> None:
    """Raise FolderNotFound unless this folder exists and belongs to user_id."""
    folder = (
        await session.execute(select(Folder.id).where(Folder.id == folder_id, Folder.user_id == user_id))
    ).scalar_one_or_none()
    if folder is None:
        raise FolderNotFound(f"Folder {folder_id} not found.")


async def create_folder(session: AsyncSession, user_id: str, name: str) -> Folder:
    folder = Folder(user_id=user_id, name=name.strip())
    session.add(folder)
    await session.flush()
    return folder


async def rename_folder(session: AsyncSession, user_id: str, folder_id: uuid.UUID, name: str) -> Folder | None:
    """Returns the updated folder, or None if it doesn't exist or isn't owned by this user."""
    folder = (
        await session.execute(select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id))
    ).scalar_one_or_none()
    if folder is None:
        return None

    folder.name = name.strip()
    await session.flush()
    return folder


async def count_folder_items(session: AsyncSession, folder_id: uuid.UUID) -> int:
    return (
        await session.execute(select(func.count(Item.id)).where(Item.folder_id == folder_id))
    ).scalar_one()


async def list_folders(session: AsyncSession, user_id: str) -> list[FolderSummary]:
    """Every folder, newest first, with how many items are filed in each."""
    rows = (
        await session.execute(
            select(Folder, func.count(Item.id))
            .outerjoin(Item, Item.folder_id == Folder.id)
            .where(Folder.user_id == user_id)
            .group_by(Folder.id)
            .order_by(Folder.created_at.desc())
        )
    ).all()

    return [
        FolderSummary(id=folder.id, name=folder.name, item_count=count, created_at=folder.created_at)
        for folder, count in rows
    ]


async def delete_folder(session: AsyncSession, user_id: str, folder_id: uuid.UUID) -> bool:
    """Delete a folder and everything filed in it.

    The items/chunks/concept_mentions/chat_messages cascade at the database
    level (see db/schema.sql's foreign keys) -- Python only needs to sweep
    up concepts that cascade leaves with zero mentions, the same cleanup a
    single item delete does.

    Returns True if a folder was actually deleted, False if nothing
    matched (already gone, or never belonged to this user).
    """
    result = await session.execute(delete(Folder).where(Folder.id == folder_id, Folder.user_id == user_id))
    if result.rowcount == 0:
        return False

    await cleanup_orphaned_concepts(session, user_id)
    return True
