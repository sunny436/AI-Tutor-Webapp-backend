from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import Field

from app.schemas import ApiModel, RequestModel

Activity = Literal["reading", "practice", "revision", "test"]


class StudyContextIn(RequestModel):
    subject: str | None = Field(default=None, max_length=40, description="A subject code from /v1/catalog/academic.")
    chapter_id: str | None = Field(
        default=None, max_length=120, description="From GET /v1/study/chapters for this subject; needs `subject`."
    )
    activity: Activity = "reading"


class StudyStartIn(StudyContextIn):
    client_id: uuid.UUID = Field(description="This page load of the app (a new one on every load).")


class StudyContextChangeIn(StudyContextIn):
    client_id: uuid.UUID
    expected_segment_id: uuid.UUID = Field(description="The segment the client last saw; 409 if it changed since.")


class StudyTransitionIn(RequestModel):
    client_id: uuid.UUID
    expected_segment_id: uuid.UUID


class StudyBeatIn(RequestModel):
    beat_id: uuid.UUID = Field(description="New for every beat; a retry repeats it, and a repeat changes nothing.")
    client_id: uuid.UUID
    was_active: bool = Field(
        description="This client was studying (visible, on a learning view, not paused, not idle) the whole "
        "time since its previous beat."
    )
    now_active: bool = Field(description="This client is studying now.")
    study_view: bool = Field(description="A learning view is on screen.")
    visible: bool = Field(description="The page is visible.")


class SegmentOut(ApiModel):
    id: uuid.UUID
    kind: Literal["study", "paused"]
    subject: str | None
    chapter_id: str | None
    book_id: str | None
    chapter_title: str | None
    activity: Activity
    started_at: dt.datetime


class StudySessionOut(ApiModel):
    id: uuid.UUID
    status: Literal["active", "paused", "ended"]
    started_at: dt.datetime
    paused_at: dt.datetime | None
    ended_at: dt.datetime | None
    end_reason: Literal["ended", "stale", "limit"] | None = Field(
        description="ended: the student ended it; stale: no study activity for 15 minutes (or paused for 60), "
        "so it ended at the last activity; limit: it reached 8 hours."
    )
    timezone: str
    segment: SegmentOut | None = Field(description="What the session is in now; null once it has ended.")
    active_seconds: int = Field(description="Estimated active study time, credited by the server.")
    idle_seconds: int = Field(description="Studying, but no activity was observed (or not on a learning view).")
    paused_seconds: int
    duration_seconds: int = Field(description="active + idle + paused, exactly.")


class IdleThresholdsOut(ApiModel):
    reading_seconds: int = Field(description="Reading and revision: idle after this long without input.")
    solving_seconds: int = Field(description="Practice and tests: idle after this long without input.")


class StudyStateOut(ApiModel):
    session: StudySessionOut | None = Field(description="The open session (active or paused), if any.")
    last_ended: StudySessionOut | None = Field(description="The latest session that ended in the last 24 hours.")
    idle: IdleThresholdsOut
    server_time: dt.datetime


class StudyDayOut(ApiModel):
    date: dt.date
    active_seconds: int
    idle_seconds: int
    paused_seconds: int
    app_seconds: int = Field(description="Time PadhAI was open (visible or not), studying or not.")


class StudyTotalsOut(ApiModel):
    active_seconds: int
    idle_seconds: int
    paused_seconds: int
    app_seconds: int
    sessions: int


class SubjectTimeOut(ApiModel):
    subject: str | None = Field(description="A subject code; null when no subject was chosen.")
    active_seconds: int


class ChapterTimeOut(ApiModel):
    subject: str | None
    chapter_id: str
    book_id: str
    chapter_title: str
    active_seconds: int


class ActivityTimeOut(ApiModel):
    activity: Activity
    active_seconds: int


class RecentSessionOut(ApiModel):
    id: uuid.UUID
    status: Literal["active", "paused", "ended"]
    end_reason: Literal["ended", "stale", "limit"] | None
    started_at: dt.datetime
    ended_at: dt.datetime | None
    active_seconds: int
    idle_seconds: int
    paused_seconds: int
    duration_seconds: int
    subjects: list[str | None] = Field(description="Each subject the session had, in order (null: none chosen).")
    chapters: list[str] = Field(description="Each chapter title, in order.")
    activities: list[Activity]


class StudySummaryOut(ApiModel):
    timezone: str = Field(description="The time zone of `from`/`to` and of each day: the student's.")
    start: dt.date = Field(alias="from")
    end: dt.date = Field(alias="to")
    first_recorded_date: dt.date | None = Field(
        description="The first day with any study or app time ever recorded; days before it have no data "
        "(they are not listed) rather than zero."
    )
    totals: StudyTotalsOut
    days: list[StudyDayOut] = Field(description="Days from `from` (or the first recorded day) to `to`, oldest first.")
    subjects: list[SubjectTimeOut] = Field(description="Active time per subject, most first.")
    chapters: list[ChapterTimeOut] = Field(description="Active time per chapter (when one was chosen), most first.")
    activities: list[ActivityTimeOut] = Field(description="Active time per activity, most first.")
    sessions: list[RecentSessionOut] = Field(description="Sessions in the range, newest first, at most 20.")


class ChapterOut(ApiModel):
    chapter_id: str
    book_id: str
    number: int | None
    label: str | None
    title: str


class ChaptersOut(ApiModel):
    available: bool
    reason: Literal["no_class", "unavailable", "not_configured"] | None = Field(
        description="Why there is no list: no_class (set a Class 6-12 in Academic Profile), unavailable (the "
        "textbook service did not answer), not_configured."
    )
    chapters: list[ChapterOut]
