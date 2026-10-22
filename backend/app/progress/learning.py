"""The learning streak: the one place its rules live.

- **A learning day** is a day, in India time (Asia/Kolkata, for every student), on which the
  tutor fully answered at least one meaningful question, or the student answered PRACTICE_ANSWERS
  questions of question-bank tests in the chat (owner, 2026-10-15: "5 answers make a day").
  Opening the app, signing in, reading, Settings, the calendar and small talk ("hi", "thanks")
  never count; neither does a reply that failed or was stopped, a regenerated answer, a skipped
  question, nor an exercise the tutor wrote. An answer counts for the day its question was asked,
  so a question asked just before midnight still counts for that day.
- **Recorded once per answer:** the chat calls `record_learning` in the transaction that
  finishes a complete reply (app/chat/service.py), and `record_practice` in the one that records
  an answer to a bank test (app/chat/router.py). One atomic upsert per (student, day), so
  retries, tabs and devices can never make two rows for a day.
- **The streak is derived, never stored:** from the days alone, with `streaks()`. The current
  streak ends today, or yesterday while today has no learning yet (today is then "pending");
  when an India day ends without learning, the streak breaks.
- **The answer that makes a day a learning day** reports what it did to the streak
  (`StreakEvent`: started, extended or a milestone), exactly once per day; the reply's `done`
  event carries it to the app, which celebrates it.
- **Milestones** come every 7 days of a streak (7, 14, 21, … with no upper limit), each one
  notification, once per streak (app/notifications/inbox.py).
"""

from __future__ import annotations

import re
import uuid
import zoneinfo
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityDay, LearningDailyActivity, QbSetItem
from app.learning.context import TutorProgress
from app.notifications.inbox import notify
from app.progress import activity
from app.progress.activity import ONE_DAY, streaks

LEARNING_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")
MILESTONE_EVERY = 7  # days: a milestone at 7, 14, 21, … with no upper limit
PRACTICE_ANSWERS = 5  # answers to bank tests that count as one answered question (owner, 2026-10-15)
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
    last_day: date | None = None  # the latest learning day; None before the first
    previous: int = 0  # the streak that ended on `last_day`, once `current` is 0; else 0


@dataclass(frozen=True)
class StreakEvent:
    """What the answer that made a day a learning day did to the streak."""

    kind: str  # "started" (day 1), "extended", or "milestone" (every MILESTONE_EVERY days)
    streak: int


async def _learning_dates(session: AsyncSession, user_id: uuid.UUID) -> set[date]:
    rows = await session.scalars(
        select(LearningDailyActivity.activity_date).where(LearningDailyActivity.user_id == user_id)
    )
    return set(rows)


async def streak_state(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> StreakState:
    days = await _learning_dates(session, user_id)
    today = learning_date(now)
    current, longest = streaks(days, today)
    last_day = max(days, default=None)
    previous = 0
    if current == 0 and last_day is not None:  # a whole India day passed without learning
        day = last_day
        while day in days:
            previous += 1
            day -= ONE_DAY
    return StreakState(
        current=current,
        longest=longest,
        today=today,
        today_active=today in days,
        day_end=day_end(now),
        last_day=last_day,
        previous=previous,
    )


async def tutor_progress(
    session: AsyncSession,
    user_id: uuid.UUID,
    timezone: str | None,
    default_timezone: str,
    now: datetime,
    asked_at: datetime | None = None,
) -> TutorProgress:
    """What the tutor is told of how the student is doing: the header's streak, and today's
    active minutes and questions as the Progress page counts them. Always the state before the
    question being answered:
    - a new message: read before it is recorded, so the Settings preview shows exactly what the
      next message is told;
    - a regenerated answer (`asked_at`, when the question was asked): that question is left out
      of today's count, so it is told the same count as the original answer was.
    The streak counts days with a fully answered question, so an earlier completed answer to the
    same question counts, as it does in the header. Two tabs asking at once each read their own
    state; a question committing in the other tab at that moment may or may not be in it. And the
    practice record (app/progress/practice.py), once the student has answered the bank's questions."""
    from app.progress.practice import tutor_practice  # practice reads this module's India day

    state = await streak_state(session, user_id, now)
    zone = activity.zone_for(timezone, default_timezone)
    today = activity.local_date(now, zone)
    day = await session.get(ActivityDay, (user_id, today))
    questions = day.questions if day else 0
    if asked_at is not None and activity.local_date(asked_at, zone) == today:
        questions = max(0, questions - 1)
    return TutorProgress(
        streak_days=state.current,
        today_minutes=day.active_seconds // activity.MINUTE_SECONDS if day else 0,
        today_questions=questions,
        day_left=remaining_label(state.day_end - now),
        today_counts=state.today_active,
        practice=await tutor_practice(session, user_id, now),
    )


async def record_learning(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, asked_at: datetime | None = None
) -> StreakEvent | None:
    """One meaningful, fully answered question: the India day it was asked (`asked_at`, else
    `now`) becomes a learning day, or counts one more interaction. Part of the caller's
    transaction.

    Returns the streak event when this answer made that day a learning day, else None. The
    upsert returns the day's count, so exactly one answer per day gets 1, also when tabs or
    devices finish at the same moment. A milestone reached now is announced once per streak."""
    statement = insert(LearningDailyActivity).values(user_id=user_id, activity_date=learning_date(asked_at or now))
    interactions = await session.scalar(
        statement.on_conflict_do_update(
            index_elements=[LearningDailyActivity.user_id, LearningDailyActivity.activity_date],
            set_={
                "interactions": LearningDailyActivity.interactions + 1,
                "updated_at": func.clock_timestamp(),
            },
        ).returning(LearningDailyActivity.interactions)
    )
    if interactions != 1:
        return None
    state = await streak_state(session, user_id, now)
    if state.current == 0:
        return None
    if state.current % MILESTONE_EVERY:
        return StreakEvent("started" if state.current == 1 else "extended", state.current)
    # Once per streak: the key names the day this streak began (it ends today, or yesterday
    # while today is still pending), so a streak built again celebrates its milestones again.
    ends = state.today if state.today_active else state.today - ONE_DAY
    began = ends - timedelta(days=state.current - 1)
    await notify(
        session,
        user_id,
        kind="streak_milestone",
        title=f"🔥 {state.current} Day Streak!",
        body=f"You've learned for {state.current} days in a row.",
        link="/settings/streak",
        dedup_key=f"streak-milestone:{began.isoformat()}:{state.current}",
    )
    return StreakEvent("milestone", state.current)


async def record_practice(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, answered_at: datetime
) -> StreakEvent | None:
    """One answer to a question-bank test, just recorded in the caller's transaction
    (app/chat/router.py): every PRACTICE_ANSWERS-th answer of its India day counts as one fully
    answered question (record_learning), so 5 make that day a learning day.

    The count is exact: each question is answered once (the ledger's trigger), a replayed response
    never gets here, and a per-student lock makes concurrent answers (two tabs) count one after the
    other, each statement seeing the answers committed before it."""
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"practice|{user_id}"})
    start = datetime.combine(learning_date(answered_at), time(0, 0), LEARNING_ZONE).astimezone(UTC)
    answers = await session.scalar(
        select(func.count())
        .select_from(QbSetItem)
        .where(QbSetItem.user_id == user_id, QbSetItem.answered_at >= start, QbSetItem.answered_at < start + ONE_DAY)
    )
    if not answers or answers % PRACTICE_ANSWERS:
        return None
    return await record_learning(session, user_id, now, answered_at)


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
