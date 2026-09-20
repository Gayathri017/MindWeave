"""Tavily web search -- used only as a fallback when a chat question isn't
answerable from the user's own saved items. Deliberately a plain REST call
via httpx (already a dependency, same pattern as the page-scrape in
ingestion.py) rather than the official SDK, for one extra call this small.

Entirely optional: if no API key is configured, search_web returns an
empty list and callers fall back further, to the model's own general
knowledge -- the feature degrades instead of breaking.
"""

import logging

import httpx

from app.config import get_settings
from app.models.schemas import WebSource

logger = logging.getLogger(__name__)

settings = get_settings()

_TAVILY_URL = "https://api.tavily.com/search"
_TIMEOUT = 10.0


def search_web(query: str, max_results: int = 5) -> list[WebSource]:
    """Return up to max_results (title, url, content) results, or an empty
    list if Tavily isn't configured or the search fails for any reason --
    callers treat "no results" as "fall back to general knowledge", not
    as an error worth surfacing to the user.
    """
    if not settings.tavily_api_key:
        return []

    try:
        response = httpx.post(
            _TAVILY_URL,
            headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
            json={"query": query, "search_depth": "basic", "max_results": max_results},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        logger.exception("Tavily web search failed for query %r; falling back to general knowledge.", query)
        return []

    sources = []
    for result in data.get("results", []):
        try:
            sources.append(
                WebSource(title=result.get("title") or result["url"], url=result["url"], content=result.get("content", ""))
            )
        except Exception:
            # One malformed result (e.g. a non-http URL) shouldn't sink the
            # whole search -- just skip it and keep the rest.
            logger.exception("Skipping one malformed Tavily result for query %r.", query)
    return sources
