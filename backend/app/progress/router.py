from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal, get_principal
from app.db.session import get_session
from app.errors import RateLimited
from app.progress.schemas import ActivityOut, GoalsOut, ProgressDayOut, ProgressOut, ProgressWeekOut, StreakOut
from app.progress.service import DayTotals, ProgressService

router = APIRouter(prefix="/v1/progress", tags=["progress"])


def get_progress_service(request: Request, db: AsyncSession = Depends(get_session)) -> ProgressService:
    return ProgressService(db, request.app.state.settings.default_timezone)


def _day(totals: DayTotals) -> ProgressDayOut:
    return ProgressDayOut(date=totals.day, active_minutes=totals.active_minutes, questions=totals.questions)


def _met(done: int, goal: int | None) -> bool | None:
    return None if goal is None else done >= goal


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
