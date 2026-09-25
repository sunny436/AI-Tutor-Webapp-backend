"""Active time and questions per day: the Progress domain's writes, and its notion of "today".

"Active time in PadhAI" is an app-activity measure, not a claim about study:

- The web app reports a minute (POST /v1/progress/activity) while PadhAI is open and visible
  and the student interacted with it, or a reply was streaming, within the last two minutes.
- The server credits at most **one minute per UTC minute per user**. Two tabs or two devices
  reporting the same minute count once: the credit is one atomic upsert that only applies
  when the day's last credited minute is older (`last_minute_utc`).
- Days are the student's own: their chosen time zone (users.timezone), or DEFAULT_TIMEZONE
  until they choose one. A change of time zone does not rewrite past days.

Questions are counted by the chat when a message is accepted (app/chat/service.py calls
record_question in its prepare transaction), so progress has one source for them too.
"""

from __future__ import annotations

import uuid
import zoneinfo
from datetime import UTC, date, datetime

from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityDay

MINUTE_SECONDS = 60
DAY_SECONDS = 86_400


def utcnow() -> datetime:
    return datetime.now(UTC)


def zone_for(timezone: str | None, default_timezone: str) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(timezone or default_timezone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):  # a name tzdata no longer knows
        return zoneinfo.ZoneInfo(default_timezone)


def local_date(moment: datetime, zone: zoneinfo.ZoneInfo) -> date:
    return moment.astimezone(zone).date()


async def record_question(
    session: AsyncSession, user_id: uuid.UUID, timezone: str | None, default_timezone: str
) -> None:
    """Count one accepted question on the student's current day. Part of the caller's transaction."""
    today = local_date(utcnow(), zone_for(timezone, default_timezone))
    statement = insert(ActivityDay).values(user_id=user_id, local_date=today, questions=1)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[ActivityDay.user_id, ActivityDay.local_date],
            set_={"questions": ActivityDay.questions + 1},
        )
    )


async def credit_minute(
    session: AsyncSession, user_id: uuid.UUID, timezone: str | None, default_timezone: str
) -> tuple[bool, date]:
    """Credit the current UTC minute to today, unless it already was. Returns (credited, day)."""
    minute = utcnow().replace(second=0, microsecond=0)
    today = local_date(minute, zone_for(timezone, default_timezone))
    statement = insert(ActivityDay).values(
        user_id=user_id, local_date=today, active_seconds=MINUTE_SECONDS, last_minute_utc=minute
    )
    statement = statement.on_conflict_do_update(
        index_elements=[ActivityDay.user_id, ActivityDay.local_date],
        set_={
            "active_seconds": func.least(ActivityDay.active_seconds + MINUTE_SECONDS, DAY_SECONDS),
            "last_minute_utc": statement.excluded.last_minute_utc,
        },
        where=or_(
            ActivityDay.last_minute_utc.is_(None), ActivityDay.last_minute_utc < statement.excluded.last_minute_utc
        ),
    ).returning(ActivityDay.user_id)
    credited = (await session.execute(statement)).first() is not None
    return credited, today
