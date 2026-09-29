"""The learning streak: the one place its rules live.

- **A learning day** is a day, in India time (Asia/Kolkata, for every student), on which the
  tutor fully answered at least one meaningful question. Opening the app, signing in, reading,
  Settings, the calendar and small talk ("hi", "thanks") never count; neither does a reply that
  failed or was stopped, nor a regenerated answer.
- **Recorded once per answer:** the chat calls `record_learning` in the transaction that
  finishes a complete reply (app/chat/service.py). One atomic upsert per (student, day), so
  retries, tabs and devices can never make two rows for a day.
- **The streak is derived, never stored:** from the days alone, with `streaks()`. The current
  streak ends today, or yesterday while today has no learning yet (today is then "pending");
  when an India day ends without learning, the streak breaks.
- **Milestones** (3, 7, 14, 30, 50, 100, 365 days) become one notification each, once ever
  (app/notifications/inbox.py).
"""

from __future__ import annotations

import re
import uuid
import zoneinfo
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityDay, LearningDailyActivity
from app.learning.context import TutorProgress
from app.notifications.inbox import notify
from app.progress import activity
from app.progress.activity import ONE_DAY, streaks

LEARNING_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")
MILESTONES = (3, 7, 14, 30, 50, 100, 365)
MAX_RANGE_DAYS = 371
# Calendar intensity from the day's learning interactions: 1-2 -> 1, 3-5 -> 2, 6-9 -> 3, 10+ -> 4.
INTENSITY_FLOORS = (1, 3, 6, 10)

_WORD = re.compile(r"\w+", re.UNICODE)
SMALL_TALK = frozenset(
    "hi hii hey hello helo hola namaste namaskar ok okay k thanks thank you thx ty bye good morning "
    "evening night afternoon how are u r doing whats what's up sup fine great cool nice yes no yeah "
    "yep nope hmm hm lol ji sir madam bhai please pls plz test testing".split()
)


def now() -> datetime:
    """The current instant (UTC), through the one clock tests can fix (app.progress.activity)."""
    return activity.utcnow()


def learning_date(moment: datetime) -> date:
    return moment.astimezone(LEARNING_ZONE).date()


def day_end(moment: datetime) -> datetime:
    """The next India midnight after `moment` (as a UTC instant): when today's learning day ends."""
    tomorrow = learning_date(moment) + ONE_DAY
    return datetime.combine(tomorrow, time(0, 0), LEARNING_ZONE).astimezone(UTC)


def remaining_label(left: timedelta) -> str:
    minutes = max(0, int(left.total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def is_meaningful(text: str) -> bool:
    """A real question or request, not small talk: at least three words or twelve letters,
    and not made only of greetings and acknowledgements."""
    words = _WORD.findall(text.lower())
    if not words or all(word in SMALL_TALK for word in words):
        return False
    return len(words) >= 3 or sum(len(word) for word in words) >= 12


def intensity(interactions: int) -> int:
    return sum(1 for floor in INTENSITY_FLOORS if interactions >= floor)


@dataclass(frozen=True)
class StreakState:
    current: int
    longest: int
    today: date
    today_active: bool
    day_end: datetime


async def _learning_dates(session: AsyncSession, user_id: uuid.UUID) -> set[date]:
    rows = await session.scalars(
        select(LearningDailyActivity.activity_date).where(LearningDailyActivity.user_id == user_id)
    )
    return set(rows)


async def streak_state(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> StreakState:
    days = await _learning_dates(session, user_id)
    today = learning_date(now)
    current, longest = streaks(days, today)
    return StreakState(current=current, longest=longest, today=today, today_active=today in days, day_end=day_end(now))


async def tutor_progress(
    session: AsyncSession, user_id: uuid.UUID, timezone: str | None, default_timezone: str, now: datetime
) -> TutorProgress:
    """What the tutor is told of how the student is doing: the header's streak, and today's
    active minutes and questions as the Progress page counts them. Read before a new question is
    recorded, so the Settings preview shows exactly what the next message is told."""
    state = await streak_state(session, user_id, now)
    today = activity.local_date(now, activity.zone_for(timezone, default_timezone))
    day = await session.get(ActivityDay, (user_id, today))
    return TutorProgress(
        streak_days=state.current,
        today_minutes=day.active_seconds // activity.MINUTE_SECONDS if day else 0,
        today_questions=day.questions if day else 0,
    )


async def record_learning(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> StreakState:
    """One meaningful, fully answered question: today (India time) becomes a learning day, or
    counts one more interaction. Part of the caller's transaction. A milestone reached now is
    announced once."""
    statement = insert(LearningDailyActivity).values(user_id=user_id, activity_date=learning_date(now))
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[LearningDailyActivity.user_id, LearningDailyActivity.activity_date],
            set_={
                "interactions": LearningDailyActivity.interactions + 1,
                "updated_at": func.clock_timestamp(),
            },
        )
    )
    state = await streak_state(session, user_id, now)
    if state.current in MILESTONES:
        await notify(
            session,
            user_id,
            kind="streak_milestone",
            title=f"🔥 {state.current} Day Streak!",
            body=f"You've learned for {state.current} days in a row.",
            link="/settings/streak",
            dedup_key=f"streak-milestone:{state.current}",
        )
    return state


@dataclass(frozen=True)
class LearningDay:
    date: date
    interactions: int
    intensity: int


async def learning_days(session: AsyncSession, user_id: uuid.UUID, start: date, end: date) -> list[LearningDay]:
    """The student's learning days from `start` to `end` (inclusive), oldest first; days
    without learning are left out. The caller bounds the range (MAX_RANGE_DAYS)."""
    rows = await session.execute(
        select(LearningDailyActivity.activity_date, LearningDailyActivity.interactions)
        .where(
            LearningDailyActivity.user_id == user_id,
            LearningDailyActivity.activity_date >= start,
            LearningDailyActivity.activity_date <= end,
        )
        .order_by(LearningDailyActivity.activity_date)
    )
    return [LearningDay(date=day, interactions=count, intensity=intensity(count)) for day, count in rows]
