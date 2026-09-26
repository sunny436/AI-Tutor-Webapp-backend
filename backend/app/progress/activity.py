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
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityDay

MINUTE_SECONDS = 60
DAY_SECONDS = 86_400
ONE_DAY = timedelta(days=1)


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


def streaks(active_days: set[date], today: date) -> tuple[int, int]:
    """(current, longest) runs of consecutive active days. The current run ends today, or
    yesterday while today has no activity yet."""
    current = 0
    day = today if today in active_days else today - ONE_DAY
    while day in active_days:
        current += 1
        day -= ONE_DAY
    longest = run = 0
    previous: date | None = None
    for day in sorted(active_days):
        run = run + 1 if previous is not None and day == previous + ONE_DAY else 1
        longest = max(longest, run)
        previous = day
    return current, longest


@dataclass(frozen=True)
class Snapshot:
    """What reminders need to know (app/notifications/reminders.py)."""

    today: date
    today_active: bool
    current_streak: int
    last_week_start: date
    last_week_minutes: int
    last_week_questions: int
    last_week_active_days: int


async def snapshot(session: AsyncSession, user_id: uuid.UUID, zone: zoneinfo.ZoneInfo, now: datetime) -> Snapshot:
    today = local_date(now, zone)
    rows = (
        await session.execute(
            select(ActivityDay.local_date, ActivityDay.active_seconds, ActivityDay.questions).where(
                ActivityDay.user_id == user_id, ActivityDay.local_date <= today
            )
        )
    ).all()
    active = {row.local_date for row in rows if row.active_seconds >= MINUTE_SECONDS or row.questions > 0}
    last_week_start = today - timedelta(days=today.weekday() + 7)
    last_week = [row for row in rows if last_week_start <= row.local_date < last_week_start + timedelta(days=7)]
    return Snapshot(
        today=today,
        today_active=today in active,
        current_streak=streaks(active, today)[0],
        last_week_start=last_week_start,
        last_week_minutes=sum(row.active_seconds for row in last_week) // MINUTE_SECONDS,
        last_week_questions=sum(row.questions for row in last_week),
        last_week_active_days=len({row.local_date for row in last_week} & active),
    )
