"""Extracts concepts/entities from saved items and links co-occurring ones.

This is what turns Mindweave from "chat with your notes" into an actual
graph: every time an item is saved, we ask Gemini for the handful of
concepts it's really about, then record that those concepts appeared
together. Do this enough times across enough items and a real map of
your thinking emerges -- without you ever manually drawing a line
between two notes.
"""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Concept, ConceptLink, ConceptMention
from app.services.gemini_client import generate_structured
from app.services.graph_math import unique_pairs

_SYSTEM_INSTRUCTION = (
    "Extract the key concepts, entities, and topics this text is really "
    "about. Return short, specific names (2-4 words each, e.g. "
    "'knowledge graphs', not 'the idea of representing information as "
    "connected nodes'). Prefer concrete nouns and named ideas over "
    "generic words like 'thing' or 'idea'."
)


class ExtractedConcepts(BaseModel):
    concepts: list[str] = Field(
        ...,
        min_length=1,
        max_length=8,
        description="3-8 short, specific concept or entity names from the text.",
    )


def extract_concepts(text: str) -> list[str]:
    """Ask Gemini for the key concepts in a piece of text.

    Names are lowercased before returning, so "Knowledge Graphs" and
    "knowledge graphs" in two different items are treated as the same
    node rather than fragmenting the graph. Deliberate simplification --
    proper synonym/fuzzy matching is a good v2, not needed to ship v1.
    """
    result = generate_structured(text, ExtractedConcepts, system_instruction=_SYSTEM_INSTRUCTION)
    seen: set[str] = set()
    names: list[str] = []
    for name in result.concepts:
        normalized = name.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            names.append(normalized)
    return names


async def store_concepts_for_item(
    session: AsyncSession, user_id: str, item_id: uuid.UUID, concept_names: list[str]
) -> None:
    """Get-or-create each concept, record that this item mentions it, and
    increment the link weight for every pair that co-occurred here.
    """
    concept_ids: list[uuid.UUID] = []

    for name in concept_names:
        concept_id = await _get_or_create_concept(session, user_id, name)
        concept_ids.append(concept_id)
        await _record_mention(session, user_id, concept_id, item_id)

    for concept_a_id, concept_b_id in unique_pairs(concept_ids):
        await _increment_link(session, user_id, concept_a_id, concept_b_id)


async def _get_or_create_concept(session: AsyncSession, user_id: str, name: str) -> uuid.UUID:
    # ON CONFLICT DO UPDATE (even a no-op update) lets Postgres RETURNING
    # give us the id whether this was a fresh insert or an existing row --
    # a single atomic round-trip instead of select-then-maybe-insert,
    # which avoids a race if the same concept is saved twice in quick
    # succession (e.g. a double-click, or two browser tabs).
    stmt = (
        pg_insert(Concept)
        .values(user_id=user_id, name=name)
        .on_conflict_do_update(index_elements=["user_id", "name"], set_={"name": name})
        .returning(Concept.id)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def _record_mention(
    session: AsyncSession, user_id: str, concept_id: uuid.UUID, item_id: uuid.UUID
) -> None:
    stmt = (
        pg_insert(ConceptMention)
        .values(user_id=user_id, concept_id=concept_id, item_id=item_id)
        .on_conflict_do_nothing(index_elements=["concept_id", "item_id"])
    )
    await session.execute(stmt)


async def _increment_link(
    session: AsyncSession, user_id: str, concept_a_id: uuid.UUID, concept_b_id: uuid.UUID
) -> None:
    stmt = (
        pg_insert(ConceptLink)
        .values(user_id=user_id, concept_a_id=concept_a_id, concept_b_id=concept_b_id, weight=1)
        .on_conflict_do_update(
            index_elements=["concept_a_id", "concept_b_id"],
            set_={"weight": ConceptLink.weight + 1, "updated_at": func.now()},
        )
    )
    await session.execute(stmt)
