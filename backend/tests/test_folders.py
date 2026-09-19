"""Integration tests for folder CRUD and cascade-delete semantics.

Uses a real (throwaway, local) Postgres database -- see conftest.py.
Items are inserted directly via the ORM rather than through
save_item/ingestion, since ingestion needs a live Gemini key; these
tests are about the folder logic itself; extract_concepts and friends
already aren't unit tested for the same reason (see test_chunking.py).
"""

import pytest
from sqlalchemy import select

from app.models.orm import Concept, ConceptMention, Item
from app.services.folders import FolderNotFound, create_folder, delete_folder, list_folders, validate_folder_ownership

pytestmark = pytest.mark.asyncio


async def _make_item(db_session, user_id, folder_id=None, text="some text"):
    item = Item(user_id=user_id, source_type="text", raw_text=text, folder_id=folder_id)
    db_session.add(item)
    await db_session.flush()
    await db_session.commit()
    return item


async def test_create_folder_starts_empty(db_session, user_id):
    folder = await create_folder(db_session, user_id, "Research")
    await db_session.commit()

    folders = await list_folders(db_session, user_id)
    assert len(folders) == 1
    assert folders[0].id == folder.id
    assert folders[0].name == "Research"
    assert folders[0].item_count == 0


async def test_list_folders_counts_items_correctly(db_session, user_id):
    folder = await create_folder(db_session, user_id, "Papers")
    await db_session.commit()
    await _make_item(db_session, user_id, folder_id=folder.id)
    await _make_item(db_session, user_id, folder_id=folder.id)
    await _make_item(db_session, user_id, folder_id=None)  # unfiled -- shouldn't count

    folders = await list_folders(db_session, user_id)
    assert folders[0].item_count == 2


async def test_folders_are_scoped_to_their_owner(db_session, user_id, other_user_id):
    await create_folder(db_session, user_id, "Mine")
    await db_session.commit()

    other_users_folders = await list_folders(db_session, other_user_id)
    assert other_users_folders == []


async def test_validate_folder_ownership_rejects_another_users_folder(db_session, user_id, other_user_id):
    folder = await create_folder(db_session, user_id, "Mine")
    await db_session.commit()

    with pytest.raises(FolderNotFound):
        await validate_folder_ownership(db_session, other_user_id, folder.id)


async def test_validate_folder_ownership_rejects_nonexistent_folder(db_session, user_id):
    import uuid

    with pytest.raises(FolderNotFound):
        await validate_folder_ownership(db_session, user_id, uuid.uuid4())


async def test_delete_folder_deletes_its_items_too(db_session, user_id):
    folder = await create_folder(db_session, user_id, "Temp")
    await db_session.commit()
    item = await _make_item(db_session, user_id, folder_id=folder.id)
    other_item = await _make_item(db_session, user_id, folder_id=None)

    deleted = await delete_folder(db_session, user_id, folder.id)
    await db_session.commit()

    assert deleted is True
    remaining_ids = (await db_session.execute(select(Item.id).where(Item.user_id == user_id))).scalars().all()
    assert item.id not in remaining_ids
    assert other_item.id in remaining_ids  # unfiled item is untouched


async def test_delete_folder_sweeps_up_orphaned_concepts(db_session, user_id):
    folder = await create_folder(db_session, user_id, "Temp")
    await db_session.commit()
    item = await _make_item(db_session, user_id, folder_id=folder.id)

    concept = Concept(user_id=user_id, name="only mentioned here")
    db_session.add(concept)
    await db_session.flush()
    db_session.add(ConceptMention(concept_id=concept.id, item_id=item.id, user_id=user_id))
    await db_session.commit()

    await delete_folder(db_session, user_id, folder.id)
    await db_session.commit()

    remaining_concepts = (
        await db_session.execute(select(Concept.id).where(Concept.user_id == user_id))
    ).scalars().all()
    assert concept.id not in remaining_concepts


async def test_delete_folder_returns_false_when_not_found(db_session, user_id):
    import uuid

    deleted = await delete_folder(db_session, user_id, uuid.uuid4())
    assert deleted is False


async def test_delete_folder_cannot_target_another_users_folder(db_session, user_id, other_user_id):
    folder = await create_folder(db_session, user_id, "Mine")
    await db_session.commit()

    deleted = await delete_folder(db_session, other_user_id, folder.id)
    assert deleted is False

    folders = await list_folders(db_session, user_id)
    assert len(folders) == 1  # untouched
