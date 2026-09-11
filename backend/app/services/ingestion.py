"""Orchestrates turning a saved URL, note, or audio recording into searchable, embedded chunks."""

import logging

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Chunk, Item
from app.models.schemas import SaveItemRequest
from app.services.chunking import chunk_text
from app.services.dates import resolve_today
from app.services.extraction import enrich_note, extract_concepts, store_concepts_for_item
from app.services.gemini_client import embed_texts, generate_title, transcribe_audio

logger = logging.getLogger(__name__)


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
) -> Item:
    """The shared tail end of saving any item, regardless of where its text
    came from (typed, scraped, or transcribed): enforce the daily cap,
    store the item, resolve dates, chunk, embed, and extract concepts.
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


async def save_item(
    session: AsyncSession,
    user_id: str,
    request: SaveItemRequest,
    daily_limit: int,
) -> Item:
    """Save a typed note or a URL."""
    if request.source_type == "url":
        text, title = await _extract_text_from_url(request.content)
        source_url = request.content
    else:
        text, title, source_url = request.content, None, None

    return await _finish_saving_item(
        session, user_id, request.source_type, source_url, title, text, request.timezone, daily_limit
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