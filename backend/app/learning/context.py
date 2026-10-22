"""The Learning domain's public reads: what the tutor may know about a student (their settings,
and how they are doing: TutorProgress, read by app.progress.learning), the student's
active-time goals, and what their practice plan needs (read_plan_profile).

Chat reads the context once per turn, inside its prepare transaction (app/chat/service.py);
Progress reads the goals and the plan's profile (app/progress) and reminders the study time
(app/notifications). None of them touches the learning tables itself. The
context holds display names, not codes, and nothing that identifies the student: no name,
email address or photo ever reaches the model.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PREFERENCE_CHOICES, LearnerProfile, LearnerSubject, LearningPreferences
from app.learning import catalog


@dataclass(frozen=True)
class SubjectContext:
    name: str
    priority: bool = False
    needs_improvement: bool = False


@dataclass(frozen=True)
class PracticeProgress:
    """The practice record as the tutor is told it (app.progress.practice): estimates from the
    student's answers to question-bank tests, never marks."""

    weakest: tuple[str, ...] = ()  # up to 3 weak concepts, in words, weakest first
    due: tuple[tuple[str, int], ...] = ()  # up to 3 topics due for revision: (title, days overdue)
    mastered: int = 0  # concepts estimated as mastered
    answered_today: int = 0  # answers today (India day)
    learning_day_answers: int = 0  # the answers in a day that make it a learning day


@dataclass(frozen=True)
class TutorProgress:
    """How the student is doing, as the tutor is told it: the header's learning streak (India
    days) and today's active minutes and questions (the student's own day). Numbers only; read by
    app.progress.learning.tutor_progress, before the question being asked is counted."""

    streak_days: int = 0
    today_minutes: int = 0
    today_questions: int = 0
    # The header's countdown: what is left of today's learning day (India time), e.g. "9h 01m",
    # and whether today already counts toward the streak. None when not read.
    day_left: str | None = None
    today_counts: bool | None = None
    # Their practice record; None before their first answer to a question-bank test.
    practice: PracticeProgress | None = None


@dataclass(frozen=True)
class StudentContext:
    grade: str | None = None
    board: str | None = None
    board_state: str | None = None
    medium: str | None = None
    academic_year: str | None = None
    subjects: tuple[SubjectContext, ...] = ()
    main_goal: str | None = None  # a MAIN_GOALS code
    target_exam: str | None = None
    target_score_percent: int | None = None
    weak_topics: tuple[str, ...] = ()
    short_term_goal: str | None = None
    long_term_goal: str | None = None
    daily_minutes_goal: int | None = None
    weekly_minutes_goal: int | None = None
    study_time: time | None = None
    # Only the preferences that are not "auto", in PREFERENCE_CHOICES order.
    preferences: tuple[tuple[str, str], ...] = ()
    progress: TutorProgress | None = None


@dataclass(frozen=True)
class SubjectChoice:
    code: str
    is_priority: bool = False
    needs_improvement: bool = False


def _name(entries: tuple[catalog.Entry, ...], code: str | None) -> str | None:
    entry = catalog.lookup(entries, code)
    # "Other" says nothing the tutor could use.
    return entry.name if entry and entry.code != "other" else None


def subject_name(code: str | None) -> str | None:
    """A subject's name from its catalog code; None for a code the catalog doesn't have (app/study)."""
    entry = catalog.lookup(catalog.SUBJECTS, code)
    return entry.name if entry else None


def build_context(
    profile: Mapping[str, object],
    subjects: Iterable[SubjectChoice],
    preferences: Mapping[str, str],
    progress: TutorProgress | None = None,
) -> StudentContext:
    """Pure: from stored (or draft) values to what the tutor is told. `profile` and
    `preferences` map column names to values; anything missing counts as unset. `progress` is
    read by the caller (app.progress.learning.tutor_progress)."""
    board_state = _name(catalog.BOARD_STATES, profile.get("board_state")) if profile.get("board") == "state" else None
    named_subjects = []
    for subject in subjects:
        entry = catalog.lookup(catalog.SUBJECTS, subject.code)
        if entry:
            named_subjects.append(SubjectContext(entry.name, subject.is_priority, subject.needs_improvement))
    return StudentContext(
        grade=_name(catalog.GRADES, profile.get("grade")),
        board=_name(catalog.BOARDS, profile.get("board")),
        board_state=board_state,
        medium=_name(catalog.MEDIUMS, profile.get("medium")),
        academic_year=_name(catalog.ACADEMIC_YEARS, profile.get("academic_year")),
        subjects=tuple(named_subjects),
        main_goal=profile.get("main_goal"),
        target_exam=profile.get("target_exam"),
        target_score_percent=profile.get("target_score_percent"),
        weak_topics=tuple(profile.get("weak_topics") or ()),
        short_term_goal=profile.get("short_term_goal"),
        long_term_goal=profile.get("long_term_goal"),
        daily_minutes_goal=profile.get("daily_active_minutes_goal"),
        weekly_minutes_goal=profile.get("weekly_active_minutes_goal"),
        study_time=profile.get("preferred_study_time"),
        preferences=tuple(
            (name, preferences[name]) for name in PREFERENCE_CHOICES if preferences.get(name, "auto") != "auto"
        ),
        progress=progress,
    )


PROFILE_COLUMNS = tuple(column.key for column in LearnerProfile.__table__.columns)
PREFERENCE_COLUMNS = tuple(PREFERENCE_CHOICES)


def profile_values(row: LearnerProfile | None) -> dict[str, object]:
    return {column: getattr(row, column) for column in PROFILE_COLUMNS} if row else {}


def preference_values(row: LearningPreferences | None) -> dict[str, str]:
    return {column: getattr(row, column) for column in PREFERENCE_COLUMNS} if row else {}


async def read_subjects(session: AsyncSession, user_id: uuid.UUID) -> list[LearnerSubject]:
    rows = await session.scalars(
        select(LearnerSubject).where(LearnerSubject.user_id == user_id).order_by(LearnerSubject.position)
    )
    return list(rows)


def subject_choices(rows: Iterable[LearnerSubject]) -> list[SubjectChoice]:
    return [SubjectChoice(row.subject_code, row.is_priority, row.needs_improvement) for row in rows]


@dataclass(frozen=True)
class ActiveTimeGoals:
    daily_minutes: int | None = None
    weekly_minutes: int | None = None


async def read_active_time_goals(session: AsyncSession, user_id: uuid.UUID) -> ActiveTimeGoals:
    """The student's own daily and weekly active-time goals (read by app/progress)."""
    row = await session.get(LearnerProfile, user_id)
    return ActiveTimeGoals(row.daily_active_minutes_goal, row.weekly_active_minutes_goal) if row else ActiveTimeGoals()


async def read_study_time(session: AsyncSession, user_id: uuid.UUID) -> time | None:
    """When the student prefers to study, in their own time zone (read by reminders)."""
    row = await session.get(LearnerProfile, user_id)
    return row.preferred_study_time if row else None


@dataclass(frozen=True)
class PlanProfile:
    """What the practice plan needs (app/progress/practice.py): the class (6-12, else None), the
    language of the bank's books in the student's medium, their subjects in order of attention
    (priority first, then those that need work, each in their own order), the daily goal and the
    exam date."""

    class_level: int | None = None
    language: str = "english"
    subjects: tuple[str, ...] = ()
    daily_minutes_goal: int | None = None
    exam_date: date | None = None


async def read_plan_profile(session: AsyncSession, user_id: uuid.UUID) -> PlanProfile:
    profile = await session.get(LearnerProfile, user_id)
    if profile is None:
        return PlanProfile()
    grade = re.fullmatch(r"class_(\d{1,2})", profile.grade or "")
    subjects = sorted(await read_subjects(session, user_id), key=lambda s: (not s.is_priority, not s.needs_improvement))
    return PlanProfile(
        class_level=int(grade[1]) if grade and 6 <= int(grade[1]) <= 12 else None,
        language="hindi" if profile.medium == "hindi" else "english",  # the bank's books: English or Hindi
        subjects=tuple(subject.subject_code for subject in subjects),
        daily_minutes_goal=profile.daily_active_minutes_goal,
        exam_date=profile.exam_date,
    )


async def read_student_context(
    session: AsyncSession, user_id: uuid.UUID, progress: TutorProgress | None = None
) -> StudentContext:
    profile = await session.get(LearnerProfile, user_id)
    preferences = await session.get(LearningPreferences, user_id)
    subjects = await read_subjects(session, user_id) if profile else []  # subjects need a profile row
    return build_context(profile_values(profile), subject_choices(subjects), preference_values(preferences), progress)
