"""Pure combinatorial logic for building concept-graph edges.

Kept separate from extraction.py (which needs a live Gemini client and
therefore full app settings) specifically so this can be imported and
unit tested with zero external dependencies -- no API keys, no database,
no settings required, just the standard library.
"""

import itertools
import uuid


def unique_pairs(ids: list[uuid.UUID]) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Every unordered pair from a list of ids, each pair canonically
    ordered (smaller id first) so (a, b) and (b, a) are never both produced.

    Deduplicates the input first: itertools.combinations operates on list
    *positions*, not values, so a repeated id would otherwise produce a
    nonsensical self-pair like (a, a) if it appeared twice in the input.
    """
    distinct_ids = set(ids)
    pairs = {(a, b) if a < b else (b, a) for a, b in itertools.combinations(distinct_ids, 2)}
    return sorted(pairs)
