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
    current_days: int = Field(
        description="The learning streak (GET /v1/progress/streak): consecutive learning days up to today, "
        "or up to yesterday while today has none yet."
    )
    longest_days: int


class GoalsOut(ApiModel):
    daily_active_minutes: int | None
    weekly_active_minutes: int | None
    daily_met: bool | None = Field(description="Null when there is no goal.")
    weekly_met: bool | None


class LearningStreakOut(ApiModel):
    current_streak: int = Field(
        description="Consecutive learning days ending today, or ending yesterday while today has none yet "
        "(then `todayActive` is false: today is still pending). 0 once a whole India day passes without learning."
    )
    longest_streak: int
    today_active: bool = Field(description="Today (India time) is already a learning day.")
    today_date: dt.date = Field(description="Today's learning date, in `timezone`.")
    timezone: str = Field(description="The time zone of learning days: Asia/Kolkata for everyone.")
    day_end: dt.datetime = Field(description="When today's learning day ends (the next midnight in `timezone`).")
    previous_streak: int = Field(
        description="The streak that ended: its length once `currentStreak` is 0 after a whole India day "
        "without learning; 0 otherwise (also while today is only pending)."
    )
    last_learning_date: dt.date | None = Field(description="The latest learning day; null before the first.")


class LearningDayOut(ApiModel):
    date: dt.date
    interactions: int = Field(description="Meaningful, fully answered questions that day.")
    intensity: int = Field(ge=1, le=4, description="1 for 1-2 interactions, 2 for 3-5, 3 for 6-9, 4 for 10 or more.")


class LearningDaysOut(ApiModel):
    start: dt.date
    end: dt.date
    days: list[LearningDayOut] = Field(description="Learning days only, oldest first.")


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
