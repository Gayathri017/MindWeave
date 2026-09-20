"""Daily usage caps -- both per-user (so one account can't hog the whole
day) and global (so the app as a whole, across every account combined,
can't blow past what the Gemini plan actually allows in a day). Reuses
the existing items/chat_messages tables for counting rather than a
separate counters table -- one less thing to keep in sync.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class DailyLimitExceeded(Exception):
    """Raised when a per-user or app-wide daily cap has been reached --
    the cost ceiling that protects the API budget from a busy (not
    necessarily malicious) user, or from many users at once.
    """


async def _count_today(session: AsyncSession, model, *filters) -> int:
    return (
        await session.scalar(
            select(func.count()).select_from(model).where(model.created_at >= func.date_trunc("day", func.now()), *filters)
        )
    ) or 0


async def enforce_daily_limit(
    session: AsyncSession,
    model,
    per_user_filter,
    per_user_limit: int,
    global_limit: int,
    what: str,
) -> None:
    """Raise DailyLimitExceeded if either this user's count or the whole
    app's count for `model` today has reached its cap. Checked in that
    order so a user hitting their own cap gets that message rather than
    the more alarming "the whole app is at capacity" one.
    """
    user_count = await _count_today(session, model, per_user_filter)
    if user_count >= per_user_limit:
        raise DailyLimitExceeded(f"Daily {what} limit of {per_user_limit} reached.")

    global_count = await _count_today(session, model)
    if global_count >= global_limit:
        raise DailyLimitExceeded(
            f"Mindweave has hit its shared daily {what} limit for today -- please try again tomorrow."
        )
