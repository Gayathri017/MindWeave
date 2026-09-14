"""Extracts concepts/entities from saved items and links co-occurring ones.

This is what turns Mindweave from "chat with your notes" into an actual
graph: every time an item is saved, we ask Gemini for the handful of
concepts it's really about, then record that those concepts appeared
together. Do this enough times across enough items and a real map of
your thinking emerges -- without you ever manually drawing a line
between two notes.
"""

import uuid
from datetime import date

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Concept, ConceptLink, ConceptMention
from app.services.gemini_client import generate_structured, generate_structured_from_file
from app.services.graph_math import unique_pairs

_CONCEPTS_SYSTEM_INSTRUCTION = (
    "Extract the key concepts, entities, and topics this text is really "
    "about. Return short, specific names (2-4 words each, e.g. "
    "'knowledge graphs', not 'the idea of representing information as "
    "connected nodes'). Prefer concrete nouns and named ideas over "
    "generic words like 'thing' or 'idea'."
)

_ENRICH_SYSTEM_INSTRUCTION_TEMPLATE = (
    "The user wrote this on {reference_date}. Do two things in one pass: "
    "(1) rewrite the text, resolving any relative date or time references "
    "-- 'tomorrow', 'next Monday', 'in two weeks', 'yesterday', etc. -- by "
    "adding the actual calendar date in parentheses right after each one, "
    "e.g. 'tomorrow (Thursday, September 10, 2026)', keeping every other "
    "word as close to the original as possible; if there are no relative "
    "date references, leave the text completely unchanged. (2) Extract "
    "3-8 short, specific concept or entity names (2-4 words each) the "
    "text is really about -- concrete nouns and named ideas, not generic "
    "words like 'thing' or 'idea'."
)


class ExtractedConcepts(BaseModel):
    concepts: list[str] = Field(
        ...,
        min_length=1,
        max_length=8,
        description="3-8 short, specific concept or entity names from the text.",
    )


class _EnrichedNote(BaseModel):
    resolved_text: str = Field(
        ..., description="The text with relative dates resolved to absolute ones, or unchanged if there were none."
    )
    concepts: list[str] = Field(
        ...,
        min_length=1,
        max_length=8,
        description="3-8 short, specific concept or entity names from the text.",
    )


_DOCUMENT_SYSTEM_INSTRUCTION = (
    "You are reading an uploaded document or photo, which could be almost "
    "anything -- a research paper, a receipt or invoice, a form, a letter, "
    "a screenshot, a scanned page. Classify it and pull out everything of "
    "value:\n"
    "- document_type: a short, specific label, e.g. 'receipt', 'invoice', "
    "'research paper', 'form', 'letter', 'other'.\n"
    "- full_text: the complete text content, transcribed as accurately as "
    "possible, in whatever language it's written in -- don't translate it. "
    "For a receipt/invoice this can be brief (vendor, date, totals); for a "
    "paper or long document, include the full body text.\n"
    "- key_fields: any distinct named values worth pulling out on their "
    "own, as plain string key/value pairs -- e.g. for a receipt: vendor, "
    "date, subtotal, tax, total, payment_method; for a paper: title, "
    "authors, journal, publication_date. Omit any field that isn't present "
    "-- don't guess or invent values.\n"
    "- line_items: for a receipt, invoice, or itemized bill, one entry per "
    "line (description, quantity, unit_price, amount). Leave empty for "
    "documents with no itemized list.\n"
    "- figures: for a paper, report, or slide deck, one entry per figure, "
    "chart, graph, or table (label like 'Figure 2' or 'Table 1', its "
    "caption if present, and a description of what it actually shows -- "
    "the trend, the comparison, the data -- not just the caption restated). "
    "Leave empty if the document has no figures."
)


class ExtractedLineItem(BaseModel):
    description: str
    quantity: str | None = Field(default=None, description="Quantity as written, e.g. '2' or '1.5 kg'.")
    unit_price: str | None = Field(default=None, description="Price per unit as written, with currency symbol if shown.")
    amount: str | None = Field(default=None, description="Line total as written, with currency symbol if shown.")


class ExtractedFigure(BaseModel):
    label: str = Field(..., description="e.g. 'Figure 2', 'Table 1', 'Chart'.")
    caption: str | None = Field(default=None, description="The figure's own caption, if it has one.")
    description: str = Field(..., description="What the figure/graph/chart actually shows.")


class DocumentExtraction(BaseModel):
    document_type: str = Field(..., description="Short classification, e.g. 'receipt', 'research paper', 'form'.")
    full_text: str = Field(..., description="The document's full text content, in its original language.")
    key_fields: dict[str, str] = Field(
        default_factory=dict, description="Named values worth surfacing on their own, e.g. vendor/total/date."
    )
    line_items: list[ExtractedLineItem] = Field(default_factory=list)
    figures: list[ExtractedFigure] = Field(default_factory=list)


def extract_document_content(file_bytes: bytes, mime_type: str) -> DocumentExtraction:
    """Ask Gemini to read an uploaded document/image and pull out both its
    plain text and whatever structured data applies -- a receipt's line
    items and totals, a paper's figures, or just full_text with everything
    else left empty for a document that's genuinely unstructured.
    """
    return generate_structured_from_file(
        file_bytes, mime_type, DocumentExtraction, system_instruction=_DOCUMENT_SYSTEM_INSTRUCTION
    )


def _normalize_concept_names(names: list[str]) -> list[str]:
    """Lowercase and de-duplicate, so "Knowledge Graphs" and "knowledge
    graphs" in two different items are treated as the same node rather
    than fragmenting the graph. Deliberate simplification -- proper
    synonym/fuzzy matching is a good v2, not needed to ship v1.
    """
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        normalized = name.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def extract_concepts(text: str) -> list[str]:
    """Ask Gemini for the key concepts in a piece of text.

    Used on its own for scraped URLs, where there's no date resolution
    to combine it with (see enrich_note for typed notes and transcripts).
    """
    result = generate_structured(text, ExtractedConcepts, system_instruction=_CONCEPTS_SYSTEM_INSTRUCTION)
    return _normalize_concept_names(result.concepts)


def enrich_note(text: str, reference_date: date) -> tuple[str, list[str]]:
    """Resolve relative dates AND extract concepts in a single Gemini call.

    These used to be two separate calls that both read the same text --
    combining them halves the API usage (and the rate-limit exposure) for
    every typed note and voice transcript, with no loss of quality.
    Returns (resolved_text, concept_names).
    """
    system_instruction = _ENRICH_SYSTEM_INSTRUCTION_TEMPLATE.format(
        reference_date=reference_date.strftime("%A, %B %d, %Y"),
    )
    result = generate_structured(text, _EnrichedNote, system_instruction=system_instruction)
    return result.resolved_text, _normalize_concept_names(result.concepts)


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