"""Orchestrates turning a saved URL, note, or audio recording into searchable, embedded chunks."""

import logging
import re

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select
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
from app.services.gemini_client import embed_texts, generate_title, transcribe_audio

logger = logging.getLogger(__name__)

_YOUTUBE_URL_PATTERN = re.compile(r"^https?://(www\.|m\.)?(youtube\.com/(watch|shorts/)|youtu\.be/)", re.IGNORECASE)


class DailyLimitExceeded(Exception):
    """Raised when a user has hit their daily save limit -- this is the cost
    ceiling that protects the API budget from a busy (not malicious) user."""


async def _extract_text_from_url(url: str) -> tuple[str, str | None]:
    """Fetch a URL and return (plain_text, page_title).

    Deliberately simple: strips scripts/styles and returns visible text.
    Good enough for articles and blog posts; not a general-purpose scraper.
    """
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": "MindweaveBot/0.1"})
        response.raise_for_status()

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
    extracted_data: dict | None = None,
) -> Item:
    """The shared tail end of saving any item, regardless of where its text
    came from (typed, scraped, transcribed, or extracted from a document):
    enforce the daily cap, store the item, resolve dates, chunk, embed, and
    extract concepts.
    """
    today_count = await session.scalar(
        select(func.count()).select_from(Item).where(
            Item.user_id == user_id,
            Item.created_at >= func.date_trunc("day", func.now()),
        )
    )
    if today_count is not None and today_count >= daily_limit:
        raise DailyLimitExceeded(f"Daily save limit of {daily_limit} reached.")

    item = Item(
        user_id=user_id,
        source_type=source_type,
        source_url=source_url,
        title=title,
        raw_text=text,
        extracted_data=extracted_data,
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
            text_for_retrieval, concept_names = enrich_note(text, reference_date)
        except Exception:
            logger.exception("Enrichment failed for item %s; using original text, no concepts.", item.id)
    else:
        try:
            concept_names = extract_concepts(text)
        except Exception:
            logger.exception("Concept extraction failed for item %s; item was still saved.", item.id)

    pieces = chunk_text(text_for_retrieval)
    if pieces:
        vectors = embed_texts(pieces)
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
        extraction = extract_youtube_content(url)
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
        extracted_data=extracted_data,
    )


async def save_audio_item(
    session: AsyncSession,
    user_id: str,
    audio_bytes: bytes,
    mime_type: str,
    timezone: str | None,
    daily_limit: int,
) -> Item:
    """Transcribe a recording (live-captured or an uploaded audio file --
    to the backend, both are just audio bytes) and save it the same way
    as any other item.
    """
    transcript = transcribe_audio(audio_bytes, mime_type)
    title = generate_title(transcript)
    return await _finish_saving_item(session, user_id, "audio", None, title, transcript, timezone, daily_limit)


async def save_document_item(
    session: AsyncSession,
    user_id: str,
    file_bytes: bytes,
    mime_type: str,
    timezone: str | None,
    daily_limit: int,
) -> Item:
    """Extract a document or photo -- a research paper, a receipt, a form,
    whatever it turns out to be -- and save it the same way as any other
    item, with the structured fields it found alongside the plain text.
    """
    extraction = extract_document_content(file_bytes, mime_type)
    title = extraction.key_fields.get("title") or generate_title(extraction.full_text)
    extracted_data = {
        "document_type": extraction.document_type,
        "key_fields": extraction.key_fields,
        "line_items": [item.model_dump() for item in extraction.line_items],
        "figures": [figure.model_dump() for figure in extraction.figures],
    }
    return await _finish_saving_item(
        session,
        user_id,
        "document",
        None,
        title,
        extraction.full_text,
        timezone,
        daily_limit,
        extracted_data=extracted_data,
    )