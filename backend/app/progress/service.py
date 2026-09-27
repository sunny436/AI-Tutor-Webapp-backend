"""Progress summaries: today, this week, the streak and the student's goals.

Active time and questions are per day in the student's own time zone. The streak is the
learning streak (app/progress/learning.py: meaningful, fully answered questions, India time),
the same one the header and Settings > Learning & Streak show. Weeks start on Monday.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityDay
from app.learning.context import ActiveTimeGoals, read_active_time_goals
from app.progress import activity
from app.progress.learning import streak_state


@dataclass(frozen=True)
class DayTotals:
    day: date
    active_minutes: int = 0
    questions: int = 0

    @property
    def active(self) -> bool:
        return self.active_minutes > 0 or self.questions > 0


@dataclass(frozen=True)
class Summary:
    timezone: str
    timezone_is_default: bool
    today: DayTotals
    week_start: date
    week_active_minutes: int
    week_questions: int
    current_streak: int
    longest_streak: int
    goals: ActiveTimeGoals
    days: list[DayTotals]


class ProgressService:
    def __init__(self, db: AsyncSession, default_timezone: str) -> None:
        self.db = db
        self.default_timezone = default_timezone

    async def credit_minute(self, user_id: uuid.UUID, timezone: str | None) -> tuple[bool, date]:
        credited, day = await activity.credit_minute(self.db, user_id, timezone, self.default_timezone)
        await self.db.commit()
        return credited, day

    async def summary(self, user_id: uuid.UUID, timezone: str | None, days: int) -> Summary:
        zone = activity.zone_for(timezone, self.default_timezone)
        today = activity.local_date(activity.utcnow(), zone)
        rows = await self.db.execute(
            select(ActivityDay.local_date, ActivityDay.active_seconds, ActivityDay.questions).where(
                ActivityDay.user_id == user_id
            )
        )
        totals = {
            row.local_date: DayTotals(row.local_date, row.active_seconds // activity.MINUTE_SECONDS, row.questions)
            for row in rows
        }
        totals = {day: value for day, value in totals.items() if day <= today}  # a later zone can't add the future
        streak = await streak_state(self.db, user_id, activity.utcnow())
        week_start = today - timedelta(days=today.weekday())
        week = [value for day, value in totals.items() if week_start <= day <= today]
        return Summary(
            timezone=zone.key,
            timezone_is_default=not timezone or zone.key != timezone,
            today=totals.get(today, DayTotals(today)),
            week_start=week_start,
            week_active_minutes=sum(value.active_minutes for value in week),
            week_questions=sum(value.questions for value in week),
            current_streak=streak.current,
            longest_streak=streak.longest,
            goals=await read_active_time_goals(self.db, user_id),
            days=[
                totals.get(day, DayTotals(day)) for day in (today - timedelta(days=n) for n in range(days - 1, -1, -1))
            ],
        )
