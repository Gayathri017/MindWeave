"""Unit tests for the pure pairing logic used to build concept links.

This lives in its own module (graph_math.py) specifically so it has zero
external dependencies -- no Gemini client, no database, no settings --
unlike extract_concepts and store_concepts_for_item, which need a live
API key and a real database and so aren't unit tested here (same
reasoning as ingestion/retrieval in test_chunking.py).
"""

import uuid

from app.services.graph_math import unique_pairs


def test_empty_list_produces_no_pairs():
    assert unique_pairs([]) == []


def test_single_id_produces_no_pairs():
    assert unique_pairs([uuid.uuid4()]) == []


def test_two_ids_produce_one_canonically_ordered_pair():
    a, b = sorted([uuid.uuid4(), uuid.uuid4()])
    # Feed them in reverse order -- the function should still canonicalize.
    result = unique_pairs([b, a])
    assert result == [(a, b)]


def test_three_ids_produce_three_unique_pairs():
    ids = sorted(uuid.uuid4() for _ in range(3))
    result = unique_pairs(ids)
    assert len(result) == 3
    assert set(result) == {
        (ids[0], ids[1]),
        (ids[0], ids[2]),
        (ids[1], ids[2]),
    }


def test_duplicate_ids_in_input_do_not_produce_duplicate_pairs():
    a, b = sorted([uuid.uuid4(), uuid.uuid4()])
    # Same pair appearing twice in input (e.g. a concept extracted twice)
    # should still only produce one pair.
    result = unique_pairs([a, b, a, b])
    assert result == [(a, b)]
