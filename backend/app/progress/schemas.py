from __future__ import annotations

import datetime as dt

from pydantic import Field

from app.schemas import ApiModel


class ActivityOut(ApiModel):
    credited: bool = Field(description="False when this minute had already been credited (another tab or device).")
    date: dt.date


class ProgressDayOut(ApiModel):
    date: dt.date
    active_minutes: int
    questions: int


class ProgressWeekOut(ApiModel):
    start_date: dt.date = Field(description="The Monday of the current week, in the student's time zone.")
    active_minutes: int
    questions: int


class StreakOut(ApiModel):
    current_days: int = Field(description="Consecutive active days up to today (or yesterday, before today's first).")
    longest_days: int


class GoalsOut(ApiModel):
    daily_active_minutes: int | None
    weekly_active_minutes: int | None
    daily_met: bool | None = Field(description="Null when there is no goal.")
    weekly_met: bool | None


class ProgressOut(ApiModel):
    timezone: str = Field(description="The time zone that decides which day is today.")
    timezone_is_default: bool = Field(description="True until the user chooses a time zone (PATCH /v1/me/profile).")
    today: ProgressDayOut
    this_week: ProgressWeekOut
    streak: StreakOut
    goals: GoalsOut
    days: list[ProgressDayOut] = Field(
        description="The last `days` days, oldest first, including days without activity."
    )
