"""Learning API models. JSON is camelCase; codes are checked against the catalog by the service.

Free text a student writes (goals, target exam, topics) is normalised on the way in: every run
of whitespace, including line breaks, becomes one space, and control and bidirectional-override
characters are removed. What is stored is what the tutor is later shown, quoted, on one line
(app/learning/tutor.py).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, StringConstraints, field_validator, model_validator

from app.db.models import MAIN_GOALS, PREFERENCE_CHOICES
from app.schemas import ApiModel, RequestModel, check_set_reset

# The longest values a student can store, which bound the tutor instructions (tests check the
# worst case against the model's input budget).
TARGET_EXAM_MAX = 80
GOAL_MAX = 280
TOPIC_MAX = 60
TOPICS_MAX = 10
SUBJECTS_MAX = 15
EXAM_DAYS_AHEAD = 730  # an exam date is from yesterday (any time zone's today) to two years ahead

_INVISIBLE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]")


def clean_text(value: object) -> object:
    if not isinstance(value, str):
        return value
    return " ".join(_INVISIBLE.sub("", value).split())


Code = Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$")]
Topic = Annotated[str, BeforeValidator(clean_text), StringConstraints(min_length=1, max_length=TOPIC_MAX)]
Clock = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]  # "HH:MM", 24-hour
MainGoal = Literal[*MAIN_GOALS]

ProfileField = Literal[
    "grade",
    "board",
    "boardState",
    "medium",
    "academicYear",
    "mainGoal",
    "targetExam",
    "targetScorePercent",
    "weakTopics",
    "dailyActiveMinutesGoal",
    "weeklyActiveMinutesGoal",
    "preferredStudyTime",
    "shortTermGoal",
    "longTermGoal",
    "examDate",
]


class LearnerProfileSet(RequestModel):
    """Fields to set. Absent fields are unchanged; `null` is not a value (use `reset`)."""

    grade: Code | None = None
    board: Code | None = None
    board_state: Code | None = Field(default=None, description="Only with board `state`.")
    medium: Code | None = None
    academic_year: Code | None = None
    main_goal: MainGoal | None = None
    target_exam: str | None = Field(default=None, min_length=1, max_length=TARGET_EXAM_MAX)
    target_score_percent: int | None = Field(default=None, ge=0, le=100)
    weak_topics: list[Topic] | None = Field(default=None, max_length=TOPICS_MAX)
    daily_active_minutes_goal: int | None = Field(default=None, ge=0, le=720)
    weekly_active_minutes_goal: int | None = Field(default=None, ge=0, le=5040)
    preferred_study_time: Clock | None = None
    short_term_goal: str | None = Field(default=None, min_length=1, max_length=GOAL_MAX)
    long_term_goal: str | None = Field(default=None, min_length=1, max_length=GOAL_MAX)
    exam_date: date | None = Field(default=None, description="The exam's day: the practice plan's exam window.")

    @field_validator("target_exam", "short_term_goal", "long_term_goal", mode="before")
    @classmethod
    def _clean(cls, value: object) -> object:
        return clean_text(value)

    @field_validator("exam_date")
    @classmethod
    def _coming(cls, value: date | None) -> date | None:
        today = datetime.now(UTC).date()
        if value is not None and not today - timedelta(days=1) <= value <= today + timedelta(days=EXAM_DAYS_AHEAD):
            raise ValueError(f"the exam date must be from yesterday to {EXAM_DAYS_AHEAD} days ahead")
        return value

    @field_validator("weak_topics")
    @classmethod
    def _distinct(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len({topic.casefold() for topic in value}) != len(value):
            raise ValueError("a topic is listed twice")
        return value


class UpdateLearnerProfileRequest(RequestModel):
    """`{version, set, reset}` (docs/api-contract.md, "Versioned edits")."""

    version: int = Field(ge=0)
    set: LearnerProfileSet = Field(default_factory=LearnerProfileSet)
    reset: list[ProfileField] = Field(default_factory=list, max_length=len(LearnerProfileSet.model_fields))

    @model_validator(mode="after")
    def _one_meaning_per_field(self) -> UpdateLearnerProfileRequest:
        check_set_reset(self.set, self.reset)
        return self


class LearnerProfileOut(ApiModel):
    version: int = Field(description="Send it back with PATCH /v1/learning/profile.")
    grade: str | None
    board: str | None
    board_state: str | None
    medium: str | None
    academic_year: str | None
    main_goal: MainGoal | None
    target_exam: str | None
    target_score_percent: int | None
    weak_topics: list[str]
    daily_active_minutes_goal: int | None
    weekly_active_minutes_goal: int | None
    preferred_study_time: str | None = Field(description='"HH:MM", 24-hour, in the user\'s time zone.')
    short_term_goal: str | None
    long_term_goal: str | None
    exam_date: date | None
    updated_at: datetime | None


# ------------------------------------------------------------------------- subjects
class SubjectIn(RequestModel):
    code: Code
    is_priority: bool = False
    needs_improvement: bool = False


class ReplaceSubjectsRequest(RequestModel):
    """The whole list, in the order to show it. Replaces the stored list."""

    version: int = Field(ge=0)
    items: list[SubjectIn] = Field(max_length=SUBJECTS_MAX)

    @field_validator("items")
    @classmethod
    def _distinct(cls, value: list[SubjectIn]) -> list[SubjectIn]:
        if len({item.code for item in value}) != len(value):
            raise ValueError("a subject is listed twice")
        return value


class SubjectOut(ApiModel):
    code: str
    is_priority: bool
    needs_improvement: bool


class SubjectsOut(ApiModel):
    version: int = Field(description="Send it back with PUT /v1/learning/subjects.")
    items: list[SubjectOut]


# ---------------------------------------------------------------------- preferences
def _choice(name: str):
    return Literal[*PREFERENCE_CHOICES[name]]


Language = _choice("language")
ExplanationLevel = _choice("explanation_level")
Pace = _choice("pace")
Difficulty = _choice("difficulty")
MoreOrFewer = _choice("real_world_examples")
Personality = _choice("personality")
ResponseLength = _choice("response_length")
AnswerMode = _choice("answer_mode")
OnOff = _choice("step_by_step")
MistakeCorrection = _choice("mistake_correction")

PreferenceField = Literal[
    "language",
    "explanationLevel",
    "pace",
    "difficulty",
    "realWorldExamples",
    "visualExplanations",
    "personality",
    "responseLength",
    "answerMode",
    "stepByStep",
    "askBeforeAnswer",
    "practiceQuestions",
    "mistakeCorrection",
    "highlightKeyConcepts",
]


class LearningPreferencesSet(RequestModel):
    """Fields to set. `auto` (the default) adds nothing to what the tutor is told."""

    language: Language | None = None
    explanation_level: ExplanationLevel | None = None
    pace: Pace | None = None
    difficulty: Difficulty | None = None
    real_world_examples: MoreOrFewer | None = None
    visual_explanations: MoreOrFewer | None = None
    personality: Personality | None = None
    response_length: ResponseLength | None = None
    answer_mode: AnswerMode | None = None
    step_by_step: OnOff | None = None
    ask_before_answer: OnOff | None = None
    practice_questions: OnOff | None = None
    mistake_correction: MistakeCorrection | None = None
    highlight_key_concepts: OnOff | None = None


class UpdateLearningPreferencesRequest(RequestModel):
    """`{version, set, reset}`; `reset` returns a field to `auto`."""

    version: int = Field(ge=0)
    set: LearningPreferencesSet = Field(default_factory=LearningPreferencesSet)
    reset: list[PreferenceField] = Field(default_factory=list, max_length=len(PREFERENCE_CHOICES))

    @model_validator(mode="after")
    def _one_meaning_per_field(self) -> UpdateLearningPreferencesRequest:
        check_set_reset(self.set, self.reset)
        return self


class LearningPreferencesOut(ApiModel):
    version: int = Field(description="Send it back with PATCH /v1/learning/preferences.")
    language: Language
    explanation_level: ExplanationLevel
    pace: Pace
    difficulty: Difficulty
    real_world_examples: MoreOrFewer
    visual_explanations: MoreOrFewer
    personality: Personality
    response_length: ResponseLength
    answer_mode: AnswerMode
    step_by_step: OnOff
    ask_before_answer: OnOff
    practice_questions: OnOff
    mistake_correction: MistakeCorrection
    highlight_key_concepts: OnOff
    updated_at: datetime | None


# -------------------------------------------------------------------- tutor preview
class TutorPreviewRequest(RequestModel):
    """Unsaved edits to preview. Each part given replaces or overlays what is stored: `profile`
    and `preferences` fields override the stored ones, `subjects` replaces the stored list.
    Nothing is saved."""

    profile: LearnerProfileSet | None = None
    subjects: list[SubjectIn] | None = Field(default=None, max_length=SUBJECTS_MAX)
    preferences: LearningPreferencesSet | None = None


class TutorPreviewOut(ApiModel):
    instructions: str = Field(
        description="Exactly what the student's settings add to the tutor's instructions; empty when nothing."
    )
    max_chars: int


# -------------------------------------------------------------------------- catalog
class CatalogEntryOut(ApiModel):
    code: str
    name: str
    deprecated: bool


class AcademicCatalogOut(ApiModel):
    version: int
    grades: list[CatalogEntryOut]
    boards: list[CatalogEntryOut]
    board_states: list[CatalogEntryOut]
    mediums: list[CatalogEntryOut]
    academic_years: list[CatalogEntryOut]
    subjects: list[CatalogEntryOut]
