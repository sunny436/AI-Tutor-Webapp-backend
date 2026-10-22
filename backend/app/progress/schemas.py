from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import Field

from app.schemas import ApiModel

QbLanguage = Literal["english", "hindi", "sanskrit"]
MasteryState = Literal["mastered", "learning", "weak", "not_enough_evidence"]
Letter = Literal["A", "B", "C", "D"]


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


# ------------------------------------------------------- the practice record (app/progress/practice.py)
# Estimates from answers to question-bank tests in the chat, never marks. Dates are India learning days.
class PracticeSummaryOut(ApiModel):
    answered: int = Field(description="Answers counted as evidence (the first to a question on a day).")
    practised_concepts: int
    mastered_concepts: int
    weak_concepts: int
    due_revisions: int
    overdue_revisions: int
    recurring_mistakes: int


class PracticeTaskOut(ApiModel):
    kind: Literal["revise", "strengthen", "learn"]
    reason: Literal["overdue", "due", "weak_concept", "next_topic", "start_here"]
    subject_code: str
    class_level: int
    language: QbLanguage
    book_title: str
    chapter_id: str
    chapter_number: int
    chapter_title: str
    topic_id: str
    topic_number: int
    topic_title: str
    concept_tag: str | None
    estimate: float | None
    due_date: dt.date | None
    overdue_days: int | None
    questions: int
    minutes: int
    prompt: str = Field(description="The request the task puts in a new chat; the student sends it.")
    answered_today: int
    done: bool


class PracticePlanOut(ApiModel):
    date: dt.date
    timezone: str
    budget_minutes: int
    budget_source: Literal["goal", "default"]
    insufficient_history: bool
    needs_profile: bool = Field(description="No class 6-12, or none of the student's subjects is in the bank.")
    exam_date: dt.date | None
    days_to_exam: int | None
    answered_today: int
    answers_for_learning_day: int
    summary: PracticeSummaryOut
    tasks: list[PracticeTaskOut] = Field(description="At most 6, chosen from the answers before today.")


class MasteryModelOut(ApiModel):
    method: Literal["bkt"]
    prior: float
    learn: float
    guess: float
    slip: float
    mastered_at: float
    min_answers: int
    min_questions: int


class ConceptMasteryOut(ApiModel):
    concept_tag: str
    objective: str
    estimate: float
    state: MasteryState
    answered: int
    correct: int
    distinct_questions: int
    last_answered_at: dt.datetime


class TopicMasteryOut(ApiModel):
    topic_id: str
    number: int
    title: str
    estimate: float | None
    state: MasteryState
    coverage: float
    concept_count: int
    concepts: list[ConceptMasteryOut]


class ChapterMasteryOut(ApiModel):
    chapter_id: str
    number: int
    title: str
    book_title: str
    estimate: float | None
    coverage: float
    topic_count: int
    topics: list[TopicMasteryOut]


class SubjectMasteryOut(ApiModel):
    subject_code: str
    class_level: int
    language: QbLanguage
    estimate: float | None
    coverage: float
    chapters: list[ChapterMasteryOut]


class MasteryOut(ApiModel):
    model: MasteryModelOut
    answered: int
    revised_answers: int = Field(description="Answers set aside: their question was edited after it was served.")
    subjects: list[SubjectMasteryOut] = Field(description="Practised ones only.")


class RevisionOut(ApiModel):
    topic_id: str
    topic_title: str
    topic_number: int
    chapter_id: str
    chapter_title: str
    chapter_number: int
    book_title: str
    subject_code: str
    class_level: int
    state: Literal["overdue", "due", "done", "upcoming"]
    due_date: dt.date
    overdue_days: int
    interval_days: int
    recall: float
    last_reviewed: dt.date
    last_accuracy: float
    reviews: int
    estimate: float | None
    prompt: str


class RevisionsOut(ApiModel):
    date: dt.date
    ladder_days: list[int]
    items: list[RevisionOut] = Field(description="Overdue, due (by forgetting risk), done, then upcoming (by date).")


class RecurringRuleOut(ApiModel):
    wrong: int
    days: int


class MistakeOut(ApiModel):
    question_id: str
    answered_at: dt.datetime
    stem: str
    options: list[str]
    chosen: Letter
    correct: Letter
    explanation: str
    conversation_id: uuid.UUID | None = Field(description="The chat of the test; null once it is deleted.")


class MistakeConceptOut(ApiModel):
    topic_id: str
    topic_title: str
    chapter_id: str
    chapter_title: str
    chapter_number: int
    book_title: str
    subject_code: str
    class_level: int
    concept_tag: str
    objective: str
    wrong: int
    wrong_14d: int = Field(alias="wrong14d")
    recurring: bool
    state: MasteryState
    prompt: str
    items: list[MistakeOut]


class MistakesOut(ApiModel):
    recurring_rule: RecurringRuleOut
    concepts: list[MistakeConceptOut]


class PracticeTestOut(ApiModel):
    set_id: uuid.UUID
    message_id: uuid.UUID | None
    conversation_id: uuid.UUID | None = Field(description="Null once that chat is deleted.")
    title: str
    chapter_ids: list[str]
    started_at: dt.datetime
    total: int
    served: int
    answered: int
    correct: int
    open: bool


class PracticeTestsOut(ApiModel):
    items: list[PracticeTestOut]


class PracticeTopicOut(ApiModel):
    topic_id: str
    number: int
    title: str
    questions: int


class PracticeChapterOut(ApiModel):
    chapter_id: str
    number: int
    title: str
    questions: int
    topics: list[PracticeTopicOut]


class PracticeBookOut(ApiModel):
    book_id: str
    title: str
    language: QbLanguage
    chapters: list[PracticeChapterOut]


class PracticeSubjectOut(ApiModel):
    subject_code: str
    books: list[PracticeBookOut]


class PracticeTopicsOut(ApiModel):
    available: bool
    reason: Literal["no_class", "no_questions"] | None
    class_level: int | None
    language: Literal["english", "hindi"]
    subjects: list[PracticeSubjectOut]
