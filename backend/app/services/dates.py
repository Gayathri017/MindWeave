"""Resolves relative date references in saved notes into absolute dates.

Pure semantic search has no way to know "tomorrow" refers to a specific
calendar date -- two notes that both say "tomorrow" look equally similar
to an embedding model even if they were written months apart. Rewriting
relative references into absolute dates at save time, anchored to the
day the note was actually written, means both retrieval and the final
chat answer can reason about real dates instead of vague relative ones.
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.gemini_client import generate_structured

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTION_TEMPLATE = (
    "The user wrote this note on {reference_date}. Rewrite the text, "
    "keeping every word as close to the original as possible, but "
    "wherever it mentions a relative date or time -- 'tomorrow', 'next "
    "Monday', 'in two weeks', 'yesterday', etc. -- add the actual "
    "calendar date in parentheses right after it, e.g. 'tomorrow "
    "(Thursday, September 10, 2026)'. If the text has no relative date "
    "references at all, return it completely unchanged."
)


class _ResolvedText(BaseModel):
    text: str = Field(..., description="The rewritten text with resolved dates, or the original if unchanged.")


def resolve_today(timezone_name: str | None) -> date:
    """Today in `timezone_name`, falling back to a neutral default (UTC)
    if none was given or it isn't a real IANA timezone. There's no single
    "home" timezone for this app -- whoever is saving a note should get
    their own local date, not a fixed region baked into the server.
    """
    settings = get_settings()
    name = timezone_name or settings.default_timezone
    try:
        tz = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unrecognized timezone %r; falling back to %s.", name, settings.default_timezone)
        tz = ZoneInfo(settings.default_timezone)
    return datetime.now(tz).date()


def resolve_relative_dates(text: str, reference_date: date) -> str:
    """Rewrite relative date phrases in `text` into absolute ones, anchored to `reference_date`."""
    system_instruction = _SYSTEM_INSTRUCTION_TEMPLATE.format(
        reference_date=reference_date.strftime("%A, %B %d, %Y"),
    )
    result = generate_structured(text, _ResolvedText, system_instruction=system_instruction)
    return result.text