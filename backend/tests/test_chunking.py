"""Unit tests for the text chunker -- pure logic, no network or DB needed.

This is the one piece of Phase 3 tested so far, deliberately: it's pure
logic with no external dependencies, so the tests are fast and meaningful.
Ingestion and retrieval get integration tests once there's a real (test)
Supabase project to run them against -- mocking both the database and
Gemini would mostly test the mocks, not the code.
"""

from app.services.chunking import chunk_text


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_short_text_returns_single_chunk():
    text = "This is a short paragraph."
    chunks = chunk_text(text, target_chars=1000)
    assert chunks == [text]


def test_long_paragraph_is_split_on_sentence_boundaries():
    sentence = "This is one sentence. "
    long_paragraph = sentence * 100  # well over target_chars
    chunks = chunk_text(long_paragraph, target_chars=200, overlap_chars=20)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 220  # target + small tolerance from overlap


def test_multiple_paragraphs_are_grouped_up_to_target_size():
    paragraphs = ["Paragraph one." for _ in range(5)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, target_chars=1000)
    assert len(chunks) == 1  # all fit comfortably under target_chars
