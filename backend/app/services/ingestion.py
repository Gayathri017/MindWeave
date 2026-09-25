"""Orchestrates turning a saved URL, note, or audio recording into searchable, embedded chunks."""

import asyncio
import logging
import re
import uuid

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Chunk, Item
from app.models.schemas import SaveItemRequest
from app.services.chunking import chunk_text
from app.services.dates import resolve_today
from app.services.extraction import (
    enrich_note,
    extract_concepts,
    extract_document_content,
    extract_youtube_content,
    store_concepts_for_item,
)
from app.services.folders import validate_folder_ownership
from app.services.gemini_client import embed_texts, generate_title, transcribe_audio
from app.services.graph_db import store_relations_for_item
from app.services.limits import DailyLimitExceeded, enforce_daily_limit
from app.services.url_safety import ensure_public_url

logger = logging.getLogger(__name__)

_YOUTUBE_URL_PATTERN = re.compile(r"^https?://(www\.|m\.)?(youtube\.com/(watch|shorts/)|youtu\.be/)", re.IGNORECASE)
_MAX_REDIRECTS = 5


async def _extract_text_from_url(url: str) -> tuple[str, str | None]:
    """Fetch a URL and return (plain_text, page_title).

    Deliberately simple: strips scripts/styles and returns visible text.
    Good enough for articles and blog posts; not a general-purpose scraper.

    Redirects are followed manually (not via httpx's follow_redirects)
    specifically so every hop gets its own SSRF check -- a URL that looks
    external at the start can still redirect to an internal address, and
    only checking the first URL would miss that entirely.
    """
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        current_url = url
        for _ in range(_MAX_REDIRECTS + 1):
            await ensure_public_url(current_url)
            response = await client.get(current_url, headers={"User-Agent": "MindweaveBot/0.1"})
            if response.is_redirect:
                current_url = str(response.next_request.url)
                continue
            response.raise_for_status()
            break
        else:
            raise httpx.TooManyRedirects(f"Exceeded {_MAX_REDIRECTS} redirects fetching {url}")

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else None
    text = " ".join(soup.get_text(separator=" ").split())
    return text, title


async def _finish_saving_item(
    session: AsyncSession,
    user_id: str,
    source_type: str,
    source_url: str | None,
    title: str | None,
    text: str,
    timezone: str | None,
    daily_limit: int,
    global_daily_limit: int,
    extracted_data: dict | None = None,
    folder_id: uuid.UUID | None = None,
) -> Item:
    """The shared tail end of saving any item, regardless of where its text
    came from (typed, scraped, transcribed, or extracted from a document):
    enforce the daily caps (per-user and app-wide), store the item, resolve
    dates, chunk, embed, and extract concepts.
    """
    await enforce_daily_limit(session, Item, Item.user_id == user_id, daily_limit, global_daily_limit, "save")

    if folder_id is not None:
        await validate_folder_ownership(session, user_id, folder_id)

    item = Item(
        user_id=user_id,
        source_type=source_type,
        source_url=source_url,
        title=title,
        raw_text=text,
        extracted_data=extracted_data,
        folder_id=folder_id,
    )
    session.add(item)
    await session.flush()  # populates item.id without committing yet

    # For the user's own words -- typed notes or spoken/transcribed ones,
    # not scraped URLs, whose "tomorrow" is relative to whenever the
    # article was written, not when it was saved -- resolve relative date
    # phrases AND extract concepts in a single combined Gemini call. This
    # is what lets a later question like "what's on 10 Sept" actually
    # find a note (or a lecture) that only ever said "tomorrow", while
    # using half the API calls of doing these as two separate requests.
    # raw_text above stays exactly as written/transcribed; only the copy
    # used for search gets the date annotations added.
    text_for_retrieval = text
    concept_names: list[str] = []

    if source_type in ("text", "audio"):
        try:
            reference_date = resolve_today(timezone)
            text_for_retrieval, concept_names = await asyncio.to_thread(enrich_note, text, reference_date)
        except Exception:
            logger.exception("Enrichment failed for item %s; using original text, no concepts.", item.id)
    else:
        try:
            concept_names = await asyncio.to_thread(extract_concepts, text)
        except Exception:
            logger.exception("Concept extraction failed for item %s; item was still saved.", item.id)

    pieces = chunk_text(text_for_retrieval)
    if pieces:
        # embed_texts is a synchronous Gemini call -- run it off the event
        # loop so one save doesn't block every other request the server is
        # handling for the seconds it takes to come back.
        vectors = await asyncio.to_thread(embed_texts, pieces)
        for content, vector in zip(pieces, vectors):
            session.add(Chunk(item_id=item.id, user_id=user_id, content=content, embedding=vector))

    if concept_names:
        try:
            await store_concepts_for_item(session, user_id, item.id, concept_names)
        except Exception:
            logger.exception("Storing concepts failed for item %s; item was still saved.", item.id)

    return item


async def _extract_youtube_or_scrape(url: str) -> tuple[str, str | None, dict | None]:
    """Return (text, title, extracted_data) for a YouTube URL.

    Tries to have Gemini actually watch the video first -- far richer than
    a scraped transcript, and YouTube's own pages are JS-rendered anyway
    so the plain scrape below returns almost nothing useful for them. On
    any failure (quota, an age-restricted/unavailable video, etc.) falls
    back to the same scrape every other URL gets, rather than failing the
    save outright.
    """
    try:
        extraction = await asyncio.to_thread(extract_youtube_content, url)
        extracted_data = {"video_url": url, "key_points": extraction.key_points}
        return extraction.summary, extraction.title, extracted_data
    except Exception:
        logger.exception("YouTube video understanding failed for %s; falling back to page scrape.", url)
        text, title = await _extract_text_from_url(url)
        return text, title, None


async def save_item(
    session: AsyncSession,
    user_id: str,
    request: SaveItemRequest,
    daily_limit: int,
    global_daily_limit: int,
) -> Item:
    """Save a typed note or a URL."""
    extracted_data = None
    if request.source_type == "url":
        if _YOUTUBE_URL_PATTERN.match(request.content):
            text, title, extracted_data = await _extract_youtube_or_scrape(request.content)
        else:
            text, title = await _extract_text_from_url(request.content)
        source_url = request.content
    else:
        text, title, source_url = request.content, None, None

    return await _finish_saving_item(
        session,
        user_id,
        request.source_type,
        source_url,
        title,
        text,
        request.timezone,
        daily_limit,
        global_daily_limit,
        extracted_data=extracted_data,
        folder_id=request.folder_id,
    )


async def save_audio_item(
    session: AsyncSession,
    user_id: str,
    audio_bytes: bytes,
    mime_type: str,
    timezone: str | None,
    daily_limit: int,
    global_daily_limit: int,
    folder_id: uuid.UUID | None = None,
) -> Item:
    """Transcribe a recording (live-captured or an uploaded audio file --
    to the backend, both are just audio bytes) and save it the same way
    as any other item.
    """
    transcript = await asyncio.to_thread(transcribe_audio, audio_bytes, mime_type)
    title = await asyncio.to_thread(generate_title, transcript)
    return await _finish_saving_item(
        session, user_id, "audio", None, title, transcript, timezone, daily_limit, global_daily_limit,
        folder_id=folder_id,
    )


async def save_document_item(
    session: AsyncSession,
    user_id: str,
    file_bytes: bytes,
    mime_type: str,
    timezone: str | None,
    daily_limit: int,
    global_daily_limit: int,
    folder_id: uuid.UUID | None = None,
) -> Item:
    """Extract a document or photo -- a research paper, a receipt, a form,
    whatever it turns out to be -- and save it the same way as any other
    item, with the structured fields it found alongside the plain text.
    """
    extraction = await asyncio.to_thread(extract_document_content, file_bytes, mime_type)
    title = extraction.key_fields.get("title") or await asyncio.to_thread(generate_title, extraction.full_text)
    extracted_data = {
        "document_type": extraction.document_type,
        "key_fields": extraction.key_fields,
        "line_items": [item.model_dump() for item in extraction.line_items],
        "figures": [figure.model_dump() for figure in extraction.figures],
    }
    item = await _finish_saving_item(
        session,
        user_id,
        "document",
        None,
        title,
        extraction.full_text,
        timezone,
        daily_limit,
        global_daily_limit,
        extracted_data=extracted_data,
        folder_id=folder_id,
    )

    if extraction.relations:
        # GraphRAG enhancement, papers/reports only -- best-effort, same as
        # concept storage above: a Neo4j hiccup must never fail a save that
        # otherwise succeeded.
        try:
            triples = [(r.subject, r.relation, r.object) for r in extraction.relations]
            await store_relations_for_item(str(user_id), str(item.id), triples)
        except Exception:
            logger.exception("Storing graph relations failed for item %s; item was still saved.", item.id)

    return item