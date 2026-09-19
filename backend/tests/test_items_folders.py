"""Integration tests for folder-scoped item listing and item filing.

See conftest.py for why this uses a real database rather than mocks.
"""

import uuid

import pytest

from app.models.orm import Item
from app.services.folders import FolderNotFound, create_folder
from app.services.items import delete_item, list_items, update_item_folder

pytestmark = pytest.mark.asyncio


async def _make_item(db_session, user_id, folder_id=None, text="some text"):
    item = Item(user_id=user_id, source_type="text", raw_text=text, folder_id=folder_id)
    db_session.add(item)
    await db_session.flush()
    await db_session.commit()
    return item


async def test_list_items_with_no_folder_filter_returns_everything(db_session, user_id):
    folder = await create_folder(db_session, user_id, "Papers")
    await db_session.commit()
    await _make_item(db_session, user_id, folder_id=folder.id)
    await _make_item(db_session, user_id, folder_id=None)

    items = await list_items(db_session, user_id)
    assert len(items) == 2


async def test_list_items_scoped_to_a_folder_excludes_unfiled_items(db_session, user_id):
    folder = await create_folder(db_session, user_id, "Papers")
    await db_session.commit()
    filed = await _make_item(db_session, user_id, folder_id=folder.id)
    await _make_item(db_session, user_id, folder_id=None)

    items = await list_items(db_session, user_id, folder_id=folder.id)
    assert [item.id for item in items] == [filed.id]


async def test_update_item_folder_files_an_unfiled_item(db_session, user_id):
    folder = await create_folder(db_session, user_id, "Papers")
    await db_session.commit()
    item = await _make_item(db_session, user_id, folder_id=None)

    updated = await update_item_folder(db_session, user_id, item.id, folder.id)
    await db_session.commit()

    assert updated.folder_id == folder.id


async def test_update_item_folder_can_unfile_back_to_main_list(db_session, user_id):
    folder = await create_folder(db_session, user_id, "Papers")
    await db_session.commit()
    item = await _make_item(db_session, user_id, folder_id=folder.id)

    updated = await update_item_folder(db_session, user_id, item.id, None)
    await db_session.commit()

    assert updated.folder_id is None


async def test_update_item_folder_raises_for_folder_owned_by_someone_else(db_session, user_id, other_user_id):
    other_folder = await create_folder(db_session, other_user_id, "Not yours")
    await db_session.commit()
    item = await _make_item(db_session, user_id, folder_id=None)

    with pytest.raises(FolderNotFound):
        await update_item_folder(db_session, user_id, item.id, other_folder.id)


async def test_update_item_folder_returns_none_for_missing_item(db_session, user_id):
    result = await update_item_folder(db_session, user_id, uuid.uuid4(), None)
    assert result is None


async def test_delete_item_does_not_affect_folder_siblings(db_session, user_id):
    folder = await create_folder(db_session, user_id, "Papers")
    await db_session.commit()
    keep = await _make_item(db_session, user_id, folder_id=folder.id)
    remove = await _make_item(db_session, user_id, folder_id=folder.id)

    deleted = await delete_item(db_session, user_id, remove.id)
    await db_session.commit()

    assert deleted is True
    items = await list_items(db_session, user_id, folder_id=folder.id)
    assert [item.id for item in items] == [keep.id]
