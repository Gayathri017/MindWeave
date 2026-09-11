"""Resolves "today" for a given timezone -- the reference point relative
date phrases in notes ("tomorrow") get resolved against.

The actual text-rewriting (turning "tomorrow" into an absolute date) now
happens together with concept extraction in one combined Gemini call --
see extraction.enrich_note -- since both read the same text and there's
no reason to ask Gemini about it twice. This module keeps only the pure,
non-Gemini part: figuring out what day it actually is for the person
saving the note.
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings

logger = logging.getLogger(__name__)


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