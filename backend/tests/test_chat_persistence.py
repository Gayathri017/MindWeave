"""Integration tests for chat history persistence and folder scoping.

_save_turn and get_chat_history are the actual persistence path
answer_question uses -- testing them directly here means real coverage
of that logic without needing a live Gemini key (answer_question itself
calls Gemini for the embedding and the answer, so it stays untested for
the same reason extract_concepts is -- see test_chunking.py).
"""

import pytest

from app.models.schemas import ChatSource
from app.services.folders import create_folder
from app.services.retrieval import _save_turn, get_chat_history

pytestmark = pytest.mark.asyncio


async def test_global_chat_history_starts_empty(db_session, user_id):
    history = await get_chat_history(db_session, user_id, folder_id=None)
    assert history == []


async def test_save_turn_persists_question_and_answer_in_order(db_session, user_id):
    await _save_turn(db_session, user_id, None, "What did I save about X?", "You saved a note about X.", [])

    history = await get_chat_history(db_session, user_id, folder_id=None)
    assert [message.role for message in history] == ["user", "answer"]
    assert history[0].text == "What did I save about X?"
    assert history[1].text == "You saved a note about X."


async def test_save_turn_persists_sources_for_citation_chips(db_session, user_id):
    source = ChatSource(id=__import__("uuid").uuid4(), title="My Paper")
    await _save_turn(db_session, user_id, None, "question", "answer", [source])

    history = await get_chat_history(db_session, user_id, folder_id=None)
    answer_message = history[1]
    assert len(answer_message.sources) == 1
    assert answer_message.sources[0].title == "My Paper"
    assert answer_message.sources[0].id == source.id


async def test_folder_chat_is_isolated_from_global_chat(db_session, user_id):
    folder = await create_folder(db_session, user_id, "Research")
    await db_session.commit()

    await _save_turn(db_session, user_id, None, "global question", "global answer", [])
    await _save_turn(db_session, user_id, folder.id, "folder question", "folder answer", [])

    global_history = await get_chat_history(db_session, user_id, folder_id=None)
    folder_history = await get_chat_history(db_session, user_id, folder_id=folder.id)

    assert [m.text for m in global_history] == ["global question", "global answer"]
    assert [m.text for m in folder_history] == ["folder question", "folder answer"]


async def test_different_folders_have_independent_chat_threads(db_session, user_id):
    folder_a = await create_folder(db_session, user_id, "A")
    folder_b = await create_folder(db_session, user_id, "B")
    await db_session.commit()

    await _save_turn(db_session, user_id, folder_a.id, "about A", "answer A", [])
    await _save_turn(db_session, user_id, folder_b.id, "about B", "answer B", [])

    history_a = await get_chat_history(db_session, user_id, folder_id=folder_a.id)
    history_b = await get_chat_history(db_session, user_id, folder_id=folder_b.id)

    assert [m.text for m in history_a] == ["about A", "answer A"]
    assert [m.text for m in history_b] == ["about B", "answer B"]
