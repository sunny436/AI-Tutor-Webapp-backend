from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal, get_principal
from app.db.session import get_session
from app.errors import AppError, RateLimited
from app.progress import learning
from app.progress.schemas import (
    ActivityOut,
    GoalsOut,
    LearningDayOut,
    LearningDaysOut,
    LearningStreakOut,
    ProgressDayOut,
    ProgressOut,
    ProgressWeekOut,
    StreakOut,
)
from app.progress.service import DayTotals, ProgressService

router = APIRouter(prefix="/v1/progress", tags=["progress"])


def get_progress_service(request: Request, db: AsyncSession = Depends(get_session)) -> ProgressService:
    return ProgressService(db, request.app.state.settings.default_timezone)


def _day(totals: DayTotals) -> ProgressDayOut:
    return ProgressDayOut(date=totals.day, active_minutes=totals.active_minutes, questions=totals.questions)


def _met(done: int, goal: int | None) -> bool | None:
    return None if goal is None else done >= goal


class InvalidRange(AppError):
    status_code, code, message = 422, "validation_error", "Choose a range of at most a year, start before end."


@router.get("/streak", response_model=LearningStreakOut)
async def get_learning_streak(principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)):
    """The learning streak: days (India time) with at least one meaningful, fully answered
    question. Computed by the server from those days; nothing about it can be set."""
    state = await learning.streak_state(db, principal.user.id, learning.now())
    return LearningStreakOut(
        current_streak=state.current,
        longest_streak=state.longest,
        today_active=state.today_active,
        today_date=state.today,
        timezone=learning.LEARNING_ZONE.key,
        day_end=state.day_end,
    )


@router.get("/learning-days", response_model=LearningDaysOut)
async def get_learning_days(
    start: dt.date | None = Query(default=None, alias="from", description="First day (default: a year ago)."),
    end: dt.date | None = Query(default=None, alias="to", description="Last day (default: today, India time)."),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    """The student's learning days for the calendar, as daily totals (never the questions)."""
    end = end or learning.learning_date(learning.now())
    start = start or end - dt.timedelta(days=364)
    if start > end or (end - start).days >= learning.MAX_RANGE_DAYS:
        raise InvalidRange()
    days = await learning.learning_days(db, principal.user.id, start, end)
    return LearningDaysOut(
        start=start,
        end=end,
        days=[LearningDayOut(date=day.date, interactions=day.interactions, intensity=day.intensity) for day in days],
    )


@router.post("/activity", response_model=ActivityOut)
async def report_activity(
    request: Request,
    principal: Principal = Depends(get_principal),
    progress: ProgressService = Depends(get_progress_service),
):
    """Report one active minute: PadhAI is open and visible, and the student interacted with it
    (or a reply was streaming) within the last two minutes. Credited at most once per minute,
    however many tabs or devices report it."""
    user_id, timezone = principal.user.id, principal.user.timezone
    if not request.app.state.activity_limiter.allow(str(user_id)):
        raise RateLimited()
    credited, day = await progress.credit_minute(user_id, timezone)
    return ActivityOut(credited=credited, date=day)


@router.get("", response_model=ProgressOut)
async def get_progress(
    days: int = Query(default=14, ge=7, le=90, description="How many recent days to list."),
    principal: Principal = Depends(get_principal),
    progress: ProgressService = Depends(get_progress_service),
):
    """Active time in PadhAI and questions asked: today, this week, the streak and the goals."""
    summary = await progress.summary(principal.user.id, principal.user.timezone, days)
    return ProgressOut(
        timezone=summary.timezone,
        timezone_is_default=summary.timezone_is_default,
        today=_day(summary.today),
        this_week=ProgressWeekOut(
            start_date=summary.week_start,
            active_minutes=summary.week_active_minutes,
            questions=summary.week_questions,
        ),
        streak=StreakOut(current_days=summary.current_streak, longest_days=summary.longest_streak),
        goals=GoalsOut(
            daily_active_minutes=summary.goals.daily_minutes,
            weekly_active_minutes=summary.goals.weekly_minutes,
            daily_met=_met(summary.today.active_minutes, summary.goals.daily_minutes),
            weekly_met=_met(summary.week_active_minutes, summary.goals.weekly_minutes),
        ),
        days=[_day(day) for day in summary.days],
    )
