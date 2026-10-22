from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal, get_principal
from app.db.session import get_session
from app.errors import AppError, RateLimited
from app.progress import learning, practice
from app.progress.schemas import (
    ActivityOut,
    GoalsOut,
    LearningDayOut,
    LearningDaysOut,
    LearningStreakOut,
    MasteryOut,
    MistakesOut,
    PracticePlanOut,
    PracticeTestsOut,
    PracticeTopicsOut,
    ProgressDayOut,
    ProgressOut,
    ProgressWeekOut,
    RevisionsOut,
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
        previous_streak=state.previous,
        last_learning_date=state.last_day,
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


@router.get("/plan", response_model=PracticePlanOut)
async def get_practice_plan(principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)):
    """Today's practice plan (India day): revisions due, weak topics, then the next new topic of each
    subject, within the daily goal. Chosen from the answers before today, so it holds all day; today's
    answers mark its tasks done. Estimates from practice, never marks (app/progress/practice.py)."""
    return await practice.plan(db, principal.user.id, learning.now())


@router.get("/mastery", response_model=MasteryOut)
async def get_mastery(principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)):
    """Estimated mastery per concept (Bayesian knowledge tracing), rolled up to topic, chapter and
    subject, from the answers to question-bank tests; practised ones only."""
    return await practice.mastery(db, principal.user.id)


@router.get("/revisions", response_model=RevisionsOut)
async def get_revisions(principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)):
    """Every practised topic's next revision (a 1-3-7-14-30-60 day ladder), overdue and due first."""
    return await practice.revisions(db, principal.user.id, learning.now())


@router.get("/mistakes", response_model=MistakesOut)
async def get_mistakes(
    limit: int = Query(default=50, ge=1, le=200, description="The newest wrong answers to list."),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    """Wrong answers to question-bank tests by concept, newest first, with each question as it was asked."""
    return await practice.mistakes(db, principal.user.id, learning.now(), limit)


@router.get("/practice-tests", response_model=PracticeTestsOut)
async def get_practice_tests(
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    """The student's question-bank tests in the chat, newest first: kept when the chat is deleted."""
    return await practice.practice_tests(db, principal.user.id, limit)


@router.get("/practice-topics", response_model=PracticeTopicsOut)
async def get_practice_topics(principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)):
    """The bank's chapters and topics the student can practise: their class (6-12), in their medium,
    and the language subjects."""
    return await practice.practice_topics(db, principal.user.id)


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
