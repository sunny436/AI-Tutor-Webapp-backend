"""The Learning domain's public reads: what the tutor may know about a student, and the
student's active-time goals.

Chat reads the context once per turn, inside its prepare transaction (app/chat/service.py);
Progress reads the goals (app/progress) and reminders the study time (app/notifications). None
of them touches the learning tables itself. The
context holds display names, not codes, and nothing that identifies the student: no name,
email address or photo ever reaches the model.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import time

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
class StudentContext:
    grade: str | None = None
    board: str | None = None
    board_state: str | None = None
    medium: str | None = None
    subjects: tuple[SubjectContext, ...] = ()
    main_goal: str | None = None  # a MAIN_GOALS code
    target_exam: str | None = None
    target_score_percent: int | None = None
    weak_topics: tuple[str, ...] = ()
    short_term_goal: str | None = None
    long_term_goal: str | None = None
    # Only the preferences that are not "auto", in PREFERENCE_CHOICES order.
    preferences: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SubjectChoice:
    code: str
    is_priority: bool = False
    needs_improvement: bool = False


def _name(entries: tuple[catalog.Entry, ...], code: str | None) -> str | None:
    entry = catalog.lookup(entries, code)
    # "Other" says nothing the tutor could use.
    return entry.name if entry and entry.code != "other" else None


def build_context(
    profile: Mapping[str, object], subjects: Iterable[SubjectChoice], preferences: Mapping[str, str]
) -> StudentContext:
    """Pure: from stored (or draft) values to what the tutor is told. `profile` and
    `preferences` map column names to values; anything missing counts as unset."""
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
        subjects=tuple(named_subjects),
        main_goal=profile.get("main_goal"),
        target_exam=profile.get("target_exam"),
        target_score_percent=profile.get("target_score_percent"),
        weak_topics=tuple(profile.get("weak_topics") or ()),
        short_term_goal=profile.get("short_term_goal"),
        long_term_goal=profile.get("long_term_goal"),
        preferences=tuple(
            (name, preferences[name]) for name in PREFERENCE_CHOICES if preferences.get(name, "auto") != "auto"
        ),
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


async def read_student_context(session: AsyncSession, user_id: uuid.UUID) -> StudentContext:
    profile = await session.get(LearnerProfile, user_id)
    preferences = await session.get(LearningPreferences, user_id)
    subjects = await read_subjects(session, user_id) if profile else []  # subjects need a profile row
    return build_context(profile_values(profile), subject_choices(subjects), preference_values(preferences))
