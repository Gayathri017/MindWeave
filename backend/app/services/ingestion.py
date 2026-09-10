"""Orchestrates turning a saved URL or note into searchable, embedded chunks."""

import logging

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Chunk, Item
from app.models.schemas import SaveItemRequest
from app.services.chunking import chunk_text
from app.services.dates import resolve_relative_dates, resolve_today
from app.services.extraction import extract_concepts, store_concepts_for_item
from app.services.gemini_client import embed_texts

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


async def save_item(
    session: AsyncSession,
    user_id: str,
    request: SaveItemRequest,
    daily_limit: int,
) -> Item:
    """Save an item, enforcing the per-user daily cap, then chunk and embed it."""
    today_count = await session.scalar(
        select(func.count()).select_from(Item).where(
            Item.user_id == user_id,
            Item.created_at >= func.date_trunc("day", func.now()),
        )
    )
    if today_count is not None and today_count >= daily_limit:
        raise DailyLimitExceeded(f"Daily save limit of {daily_limit} reached.")

    if request.source_type == "url":
        text, title = await _extract_text_from_url(request.content)
        source_url = request.content
    else:
        text, title, source_url = request.content, None, None

    item = Item(
        user_id=user_id,
        source_type=request.source_type,
        source_url=source_url,
        title=title,
        raw_text=text,
    )
    session.add(item)
    await session.flush()  # populates item.id without committing yet

    # For the user's own typed notes -- not scraped URLs, whose "tomorrow"
    # is relative to whenever the article was written, not when it was
    # saved -- resolve relative date phrases into absolute ones before
    # chunking. This is what lets a later question like "what's on 10
    # Sept" actually find a note that only ever said "tomorrow". raw_text
    # above stays exactly as the user typed it; only the copy used for
    # search gets the date annotations added.
    text_for_retrieval = text
    if request.source_type == "text":
        try:
            reference_date = resolve_today(request.timezone)
            text_for_retrieval = resolve_relative_dates(text, reference_date)
        except Exception:
            logger.exception("Date resolution failed for item %s; using original text.", item.id)

    pieces = chunk_text(text_for_retrieval)
    if pieces:
        vectors = embed_texts(pieces)
        for content, vector in zip(pieces, vectors):
            session.add(Chunk(item_id=item.id, user_id=user_id, content=content, embedding=vector))

    try:
        concept_names = extract_concepts(text)
        await store_concepts_for_item(session, user_id, item.id, concept_names)
    except Exception:
        # Concept extraction is an enhancement on top of the core save --
        # if Gemini hiccups here, the user's note and its searchability
        # (chunks/embeddings above) must still be saved successfully.
        logger.exception("Concept extraction failed for item %s; item was still saved.", item.id)

    return item