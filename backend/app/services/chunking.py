"""A small, dependency-free text chunker.

Splits on paragraph boundaries first, then falls back to sentence
boundaries for any paragraph that's still too long, so chunks stay close
to `target_chars` without cutting mid-sentence where it can be avoided.
"""

import re

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, target_chars: int = 1_000, overlap_chars: int = 150) -> list[str]:
    """Split text into overlapping chunks suitable for embedding.

    Args:
        text: The raw text to split.
        target_chars: Roughly how many characters each chunk should hold.
        overlap_chars: How much trailing context repeats at the start of the
            next chunk, so a fact split across a boundary is still
            retrievable from either side.

    Returns:
        A list of non-empty, whitespace-trimmed chunks, in order.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph

        if len(candidate) <= target_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
        current = paragraph

        # A single paragraph longer than target_chars still needs splitting.
        while len(current) > target_chars:
            split_at = _find_sentence_split(current, target_chars)
            chunks.append(current[:split_at].strip())
            # Only back up for overlap if doing so still makes forward
            # progress -- an early sentence boundary (split_at <=
            # overlap_chars) would otherwise leave `current` unchanged and
            # loop forever.
            next_start = split_at - overlap_chars if split_at > overlap_chars else split_at
            current = current[next_start:].strip()

    if current:
        chunks.append(current)

    return [c for c in chunks if c]


def _find_sentence_split(text: str, target_chars: int) -> int:
    """Find the sentence boundary closest to (but not past) target_chars."""
    window = text[:target_chars]
    matches = list(_SENTENCE_BOUNDARY.finditer(window))
    if matches:
        return matches[-1].end()
    return target_chars  # No sentence boundary found; hard-split as a fallback.
