"""Orchestrates turning a saved URL or note into searchable, embedded chunks."""

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Chunk, Item
from app.models.schemas import SaveItemRequest
from app.services.chunking import chunk_text
from app.services.gemini_client import embed_texts


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

    pieces = chunk_text(text)
    if pieces:
        vectors = embed_texts(pieces)
        for content, vector in zip(pieces, vectors):
            session.add(Chunk(item_id=item.id, user_id=user_id, content=content, embedding=vector))

    return item
