"""Study time: sessions the student starts, pauses, resumes and ends, the active time credited
inside them, and app presence. An estimate of studying, never proof of attention.

Every page load of the web app is a *client* (a tab or a device, `clientId`). Each sends a beat
every 30 s and at every change: `wasActive` (it was studying the whole time since its previous
beat: visible, on a learning view, not paused, not idle) and `nowActive`.

- **Credit** for a client's `[p, t)` (p = its previous observation, t = now, server time only)
  needs two consecutive observations from it at most CREDIT_GAP apart, both active. It is clipped
  to the session's *studying* segments, and only the part no other client already covered is
  added, so tabs and devices never add up (the database refuses overlap: 0014's EXCLUDE). Hidden,
  idle, offline or unobserved time is never credited; two or more lost beats in a row lose that span.
- **Liveness:** a session stays alive only through study actions and credited beats; it ends at its
  last activity after STALE_AFTER without one (PAUSE_LIMIT once paused), and at SESSION_LIMIT.
  Reads compute that and never write; the next write stores it.
- **Writes** run under a per-student advisory lock; a repeated beat id changes nothing; a transition
  names the segment it expects (409 if it changed) and succeeds if its target state is already there.
- **Totals:** idle = studying-segment time - credited time, so active + idle + paused = duration,
  exactly. Days are each session's own time zone (DST-aware).
- **App presence:** any beat, visible or not; a gap over APP_GAP starts a new app session.
"""

from __future__ import annotations

import re
import time as monotonic
import uuid
import zoneinfo
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

import app.progress.activity as activity  # by module: tests freeze activity.utcnow
from app.db.models import AppSession, StudyActiveInterval, StudyBeat, StudyClient, StudySegment, StudySession, User
from app.errors import Conflict, NotFound, ServiceUnavailable, ValidationFailed
from app.learning.context import read_student_context, subject_name
from app.logging import get_logger
from app.rag.errors import RagError

log = get_logger("app.study")

CREDIT_GAP = timedelta(seconds=75)
STALE_AFTER = timedelta(minutes=15)
PAUSE_LIMIT = timedelta(minutes=60)
SESSION_LIMIT = timedelta(hours=8)
APP_GAP = timedelta(minutes=3)
KEEP_CLIENTS = timedelta(days=1)
LAST_ENDED_WITHIN = timedelta(hours=24)
MAX_DAYS = 92
RECENT_SESSIONS = 20
CHAPTERS_TTL_S = 3600
SERVED_CLASSES = range(6, 13)
ZERO = timedelta(0)


# ------------------------------------------------------------------ pure rules
@dataclass(frozen=True)
class Ending:
    at: datetime
    reason: str


def ending(session: StudySession, now: datetime) -> Ending | None:
    """When an open session has ended on its own as of `now` (None: still open, or already ended)."""
    if session.ended_at is not None:
        return None
    found = []
    if session.status == "paused" and session.paused_at is not None:
        if now - session.paused_at > PAUSE_LIMIT:
            found.append(Ending(session.paused_at + PAUSE_LIMIT, "stale"))
    elif now - session.alive_at > STALE_AFTER:
        found.append(Ending(session.alive_at, "stale"))
    if now > session.started_at + SESSION_LIMIT:
        found.append(Ending(session.started_at + SESSION_LIMIT, "limit"))
    return min(found, key=lambda end: end.at) if found else None


def subtract(
    start: datetime, end: datetime, covered: Iterable[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    """The parts of [start, end) that no interval in `covered` (sorted by start) overlaps."""
    gaps, cursor = [], start
    for a, b in covered:
        if a > cursor:
            gaps.append((cursor, min(a, end)))
        cursor = max(cursor, b)
        if cursor >= end:
            break
    if cursor < end:
        gaps.append((cursor, end))
    return [(a, b) for a, b in gaps if a < b]


def split_days(start: datetime, end: datetime, zone: zoneinfo.ZoneInfo) -> Iterator[tuple[date, timedelta]]:
    """[start, end) cut at each local midnight in `zone`: (local date, length). UTC arithmetic only."""
    while start < end:
        day = start.astimezone(zone).date()
        midnight = datetime.combine(day + timedelta(days=1), time(0), tzinfo=zone).astimezone(UTC)
        cut = min(end, midnight) if midnight > start else min(end, start + timedelta(hours=1))
        yield day, cut - start
        start = cut


def seconds(span: timedelta) -> int:
    return int(span // timedelta(seconds=1))


@dataclass
class Totals:
    """Microsecond-exact sums; whole seconds only on the way out (idle derived, so the parts add up)."""

    active: timedelta = ZERO
    studying: timedelta = ZERO
    paused: timedelta = ZERO

    def out(self) -> dict[str, int]:
        active, paused, duration = seconds(self.active), seconds(self.paused), seconds(self.studying + self.paused)
        return {
            "active_seconds": active,
            "idle_seconds": duration - active - paused,
            "paused_seconds": paused,
            "duration_seconds": duration,
        }


def mode_of(activity_name: str) -> str:
    return "solving" if activity_name in ("practice", "test") else "reading"


# ------------------------------------------------------------------ views
@dataclass
class SessionView:
    """A session as it is now: stored, or ended on its own but not stored yet (reads never write)."""

    row: StudySession
    end: Ending | None
    segment: StudySegment | None = None
    totals: Totals = field(default_factory=Totals)

    @property
    def status(self) -> str:
        return "ended" if self.end else self.row.status

    @property
    def ended_at(self) -> datetime | None:
        return self.end.at if self.end else self.row.ended_at

    @property
    def end_reason(self) -> str | None:
        return self.end.reason if self.end else self.row.end_reason

    def out(self) -> dict[str, Any]:
        segment = self.segment if self.status != "ended" else None
        return {
            "id": self.row.id,
            "status": self.status,
            "started_at": self.row.started_at,
            "paused_at": self.row.paused_at if self.status == "paused" else None,
            "ended_at": self.ended_at,
            "end_reason": self.end_reason,
            "timezone": self.row.timezone,
            "segment": None
            if segment is None
            else {
                "id": segment.id,
                "kind": segment.kind,
                "subject": segment.subject_code,
                "chapter_id": segment.chapter_id,
                "book_id": segment.book_id,
                "chapter_title": segment.chapter_title,
                "activity": segment.activity,
                "started_at": segment.started_at,
            },
            **self.totals.out(),
        }


@dataclass(frozen=True)
class Context:
    subject: str | None
    chapter_id: str | None
    book_id: str | None
    chapter_title: str | None
    activity: str

    def same(self, segment: StudySegment) -> bool:
        return (self.subject, self.chapter_id, self.activity) == (
            segment.subject_code,
            segment.chapter_id,
            segment.activity,
        )


# ------------------------------------------------------------------ chapters
class ChaptersUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Chapters:
    """NCERT chapter lists from the NCERT Knowledge Service, cached an hour per class, subject and
    language. Optional: without the service, sessions simply have no chapter."""

    def __init__(self, ncert: Any | None) -> None:
        self.ncert = ncert
        self._cache: dict[tuple[int, str, str], tuple[float, list[dict[str, Any]]]] = {}

    async def list(self, class_level: int, subject: str, language: str) -> list[dict[str, Any]]:
        if self.ncert is None:
            raise ChaptersUnavailable("not_configured")
        key = (class_level, subject, language)
        hit = self._cache.get(key)
        if hit and hit[0] > monotonic.monotonic():
            return hit[1]
        try:
            chapters = await self.ncert.chapters(class_level, subject, language)
        except RagError as error:
            raise ChaptersUnavailable("unavailable") from error
        self._cache[key] = (monotonic.monotonic() + CHAPTERS_TTL_S, chapters)
        return chapters


# ------------------------------------------------------------------ service
class StudyService:
    def __init__(self, db: AsyncSession, default_timezone: str, chapters: Chapters) -> None:
        self.db = db
        self.default_timezone = default_timezone
        self.chapters = chapters

    def _zone(self, user: User) -> zoneinfo.ZoneInfo:
        return activity.zone_for(user.timezone, self.default_timezone)

    # ---- chapters and context (resolved before any lock is taken)
    async def chapter_list(self, user: User, subject: str) -> tuple[str | None, list[dict[str, Any]]]:
        """(reason there is no list, the list) for the student's class and this subject."""
        name = subject_name(subject)
        if name is None:
            raise ValidationFailed("Choose a subject from the list.", code="unknown_subject")
        student = await read_student_context(self.db, user.id)
        grade = re.fullmatch(r"Class (\d{1,2})", student.grade or "")
        if not grade or int(grade.group(1)) not in SERVED_CLASSES:
            return "no_class", []
        language = "hi" if student.medium == "Hindi" else "en"
        try:
            return None, await self.chapters.list(int(grade.group(1)), name, language)
        except ChaptersUnavailable as error:
            return error.reason, []

    async def _context(self, user: User, subject: str | None, chapter_id: str | None, activity_name: str) -> Context:
        if subject is not None and subject_name(subject) is None:
            raise ValidationFailed("Choose a subject from the list.", code="unknown_subject")
        if chapter_id is None:
            return Context(subject, None, None, None, activity_name)
        if subject is None:
            raise ValidationFailed("Choose a subject before a chapter.", code="chapter_needs_subject")
        reason, chapters = await self.chapter_list(user, subject)
        if reason in ("unavailable", "not_configured"):
            raise ServiceUnavailable("Chapters are unavailable right now. Continue without a chapter.")
        chapter = next((c for c in chapters if c["chapter_id"] == chapter_id), None)
        if chapter is None:
            raise ValidationFailed("That chapter isn't in this subject for your class.", code="unknown_chapter")
        return Context(subject, chapter["chapter_id"], chapter["book_id"], chapter["title"], activity_name)

    # ---- reads (never write)
    async def _open(self, user_id: uuid.UUID) -> StudySession | None:
        return await self.db.scalar(
            select(StudySession).where(StudySession.user_id == user_id, StudySession.ended_at.is_(None))
        )

    async def _owned(self, user_id: uuid.UUID, session_id: uuid.UUID) -> StudySession:
        row = await self.db.scalar(
            select(StudySession).where(StudySession.id == session_id, StudySession.user_id == user_id)
        )
        if row is None:
            raise NotFound()
        return row

    async def _open_segment(self, session_id: uuid.UUID) -> StudySegment | None:
        return await self.db.scalar(
            select(StudySegment).where(StudySegment.session_id == session_id, StudySegment.ended_at.is_(None))
        )

    async def _latest_beat(self, user_id: uuid.UUID) -> datetime | None:
        return await self.db.scalar(select(func.max(StudyClient.last_beat_at)).where(StudyClient.user_id == user_id))

    def _open_end(self, view: SessionView, latest_beat: datetime | None, now: datetime) -> datetime:
        """Where an open segment ends for totals: its own end once the session has ended on its own;
        now while paused; while studying, the last time any client was heard (or study activity)."""
        if view.end is not None:
            return view.end.at
        if view.row.status == "paused":
            return now
        return min(now, max(view.row.alive_at, latest_beat or view.row.alive_at))

    async def _fill(self, views: list[SessionView], now: datetime) -> dict[uuid.UUID, list[StudySegment]]:
        """Each view's open segment and totals; returns every segment by session (oldest first)."""
        if not views:
            return {}
        ids = [view.row.id for view in views]
        segments: dict[uuid.UUID, list[StudySegment]] = defaultdict(list)
        for segment in await self.db.scalars(
            select(StudySegment).where(StudySegment.session_id.in_(ids)).order_by(StudySegment.started_at)
        ):
            segments[segment.session_id].append(segment)
        active = dict(
            (
                await self.db.execute(
                    select(
                        StudySegment.session_id, func.sum(StudyActiveInterval.ended_at - StudyActiveInterval.started_at)
                    )
                    .join(StudySegment, StudySegment.id == StudyActiveInterval.segment_id)
                    .where(StudySegment.session_id.in_(ids))
                    .group_by(StudySegment.session_id)
                )
            ).all()
        )
        latest_beat = await self._latest_beat(views[0].row.user_id)
        for view in views:
            totals = Totals(active=active.get(view.row.id) or ZERO)
            for segment in segments[view.row.id]:
                if segment.ended_at is None:
                    view.segment = segment
                end = segment.ended_at or max(self._open_end(view, latest_beat, now), segment.started_at)
                if segment.kind == "study":
                    totals.studying += end - segment.started_at
                else:
                    totals.paused += end - segment.started_at
            view.totals = totals
        return segments

    async def state(self, user: User) -> dict[str, Any]:
        now = activity.utcnow()
        current, last = None, None
        row = await self._open(user.id)
        if row is not None:
            end = ending(row, now)
            if end is None:
                current = SessionView(row, None)
            else:
                last = SessionView(row, end)
        if last is None:
            ended = await self.db.scalar(
                select(StudySession)
                .where(StudySession.user_id == user.id, StudySession.ended_at > now - LAST_ENDED_WITHIN)
                .order_by(StudySession.ended_at.desc())
                .limit(1)
            )
            last = SessionView(ended, None) if ended else None
        await self._fill([view for view in (current, last) if view], now)
        return {
            "session": current.out() if current else None,
            "last_ended": last.out() if last else None,
            "server_time": now,
        }

    # ---- writes (under the student's lock)
    async def _lock(self, user_id: uuid.UUID) -> None:
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"study:{user_id}"}
        )

    async def _settle(self, row: StudySession | None, now: datetime) -> StudySession | None:
        """Store an ending the session reached on its own. Returns the session if it is still open."""
        if row is None:
            return None
        end = ending(row, now)
        if end is None:
            return row
        segment = await self._open_segment(row.id)
        at = max(end.at, segment.started_at) if segment else end.at
        if segment is not None:
            segment.ended_at = at
        row.status, row.ended_at, row.end_reason, row.paused_at = "ended", at, end.reason, None
        await self.db.flush()
        log.info("study session ended", extra={"session_id": str(row.id), "reason": end.reason})
        return None

    async def _observe(self, user_id: uuid.UUID, client_id: uuid.UUID, now: datetime, active: bool) -> None:
        statement = insert(StudyClient).values(
            user_id=user_id, client_id=client_id, last_beat_at=now, last_beat_active=active
        )
        await self.db.execute(
            statement.on_conflict_do_update(
                index_elements=[StudyClient.user_id, StudyClient.client_id],
                set_={"last_beat_at": now, "last_beat_active": active},
            )
        )

    async def _switch(
        self, row: StudySession, segment: StudySegment, kind: str, context: Context, now: datetime
    ) -> None:
        segment.ended_at = now
        await self.db.flush()  # the closed segment first: one open segment per session
        self.db.add(
            StudySegment(
                session_id=row.id,
                user_id=row.user_id,
                kind=kind,
                subject_code=context.subject,
                chapter_id=context.chapter_id,
                book_id=context.book_id,
                chapter_title=context.chapter_title,
                activity=context.activity,
                started_at=now,
            )
        )
        await self.db.flush()

    @staticmethod
    def _context_of(segment: StudySegment) -> Context:
        return Context(
            segment.subject_code, segment.chapter_id, segment.book_id, segment.chapter_title, segment.activity
        )

    async def start(
        self, user: User, client_id: uuid.UUID, subject: str | None, chapter_id: str | None, activity_name: str
    ) -> dict[str, Any]:
        """Start a session, or join the one already open (on any tab or device) as it is."""
        context = await self._context(user, subject, chapter_id, activity_name)
        await self._lock(user.id)
        now = activity.utcnow()
        row = await self._settle(await self._open(user.id), now)
        if row is not None:
            if row.status == "active":
                row.alive_at = now
                await self._observe(user.id, client_id, now, True)
        else:
            row = StudySession(
                user_id=user.id, timezone=self._zone(user).key, status="active", started_at=now, alive_at=now
            )
            self.db.add(row)
            await self.db.flush()
            self.db.add(
                StudySegment(
                    session_id=row.id,
                    user_id=user.id,
                    kind="study",
                    subject_code=context.subject,
                    chapter_id=context.chapter_id,
                    book_id=context.book_id,
                    chapter_title=context.chapter_title,
                    activity=context.activity,
                    started_at=now,
                )
            )
            await self._observe(user.id, client_id, now, True)
            log.info("study session started", extra={"session_id": str(row.id)})
        await self.db.commit()
        return await self.state(user)

    async def _transition_target(
        self, user: User, session_id: uuid.UUID
    ) -> tuple[StudySession, StudySegment | None, datetime]:
        await self._lock(user.id)
        now = activity.utcnow()
        row = await self._owned(user.id, session_id)
        open_row = await self._settle(row if row.ended_at is None else None, now)
        return row, (await self._open_segment(row.id) if open_row else None), now

    @staticmethod
    def _expect(segment: StudySegment, expected: uuid.UUID) -> None:
        if segment.id != expected:
            raise Conflict("Your study session changed on another tab or device.", code="study_state_changed")

    @staticmethod
    def _ended() -> Conflict:
        return Conflict("This study session has already ended.", code="study_session_ended")

    async def change_context(
        self,
        user: User,
        session_id: uuid.UUID,
        client_id: uuid.UUID,
        expected: uuid.UUID,
        subject: str | None,
        chapter_id: str | None,
        activity_name: str,
    ) -> dict[str, Any]:
        context = await self._context(user, subject, chapter_id, activity_name)
        row, segment, now = await self._transition_target(user, session_id)
        if segment is None:
            await self.db.commit()
            raise self._ended()
        if not context.same(segment):
            self._expect(segment, expected)
            await self._switch(row, segment, segment.kind, context, now)
            if row.status == "active":
                row.alive_at = now
                await self._observe(user.id, client_id, now, True)
        await self.db.commit()
        return await self.state(user)

    async def pause(self, user: User, session_id: uuid.UUID, client_id: uuid.UUID, expected: uuid.UUID) -> dict:
        row, segment, now = await self._transition_target(user, session_id)
        if segment is None:
            await self.db.commit()
            raise self._ended()
        if row.status == "active":
            self._expect(segment, expected)
            await self._switch(row, segment, "paused", self._context_of(segment), now)
            row.status, row.paused_at, row.alive_at = "paused", now, now
            await self._observe(user.id, client_id, now, False)
        await self.db.commit()
        return await self.state(user)

    async def resume(self, user: User, session_id: uuid.UUID, client_id: uuid.UUID, expected: uuid.UUID) -> dict:
        row, segment, now = await self._transition_target(user, session_id)
        if segment is None:
            await self.db.commit()
            raise self._ended()
        if row.status == "paused":
            self._expect(segment, expected)
            row.status, row.paused_at, row.alive_at = "active", None, now
            await self._switch(row, segment, "study", self._context_of(segment), now)
            await self._observe(user.id, client_id, now, True)
        await self.db.commit()
        return await self.state(user)

    async def end(self, user: User, session_id: uuid.UUID, client_id: uuid.UUID, expected: uuid.UUID) -> dict:
        row, segment, now = await self._transition_target(user, session_id)
        if segment is not None:
            self._expect(segment, expected)
            segment.ended_at = now
            row.status, row.ended_at, row.end_reason, row.paused_at = "ended", now, "ended", None
            await self._observe(user.id, client_id, now, False)
            log.info("study session ended", extra={"session_id": str(row.id), "reason": "ended"})
        await self.db.commit()
        return await self.state(user)

    async def _presence(self, user: User, now: datetime) -> None:
        row = await self.db.scalar(
            select(AppSession).where(AppSession.user_id == user.id, AppSession.ended_at.is_(None))
        )
        if row is not None and now - row.last_seen_at <= APP_GAP:
            row.last_seen_at = max(row.last_seen_at, now)
            return
        if row is not None:
            row.ended_at = row.last_seen_at
            await self.db.flush()
        self.db.add(AppSession(user_id=user.id, timezone=self._zone(user).key, started_at=now, last_seen_at=now))

    async def _credit(self, user_id: uuid.UUID, session_id: uuid.UUID, start: datetime, end: datetime) -> bool:
        """Credit [start, end) inside the session's studying segments, minus what is already credited."""
        credited = False
        segments = await self.db.scalars(
            select(StudySegment)
            .where(
                StudySegment.session_id == session_id,
                StudySegment.kind == "study",
                StudySegment.started_at < end,
                (StudySegment.ended_at.is_(None)) | (StudySegment.ended_at > start),
            )
            .order_by(StudySegment.started_at)
        )
        for segment in list(segments):
            a, b = max(start, segment.started_at), min(end, segment.ended_at or end)
            if a >= b:
                continue
            covered = (
                await self.db.execute(
                    select(StudyActiveInterval.started_at, StudyActiveInterval.ended_at)
                    .where(
                        StudyActiveInterval.user_id == user_id,
                        StudyActiveInterval.started_at < b,
                        StudyActiveInterval.ended_at > a,
                    )
                    .order_by(StudyActiveInterval.started_at)
                )
            ).all()
            for gap_start, gap_end in subtract(a, b, covered):
                adjacent = await self.db.scalar(
                    select(StudyActiveInterval).where(
                        StudyActiveInterval.segment_id == segment.id, StudyActiveInterval.ended_at == gap_start
                    )
                )
                if adjacent is not None:
                    adjacent.ended_at = gap_end
                else:
                    self.db.add(
                        StudyActiveInterval(
                            segment_id=segment.id, user_id=user_id, started_at=gap_start, ended_at=gap_end
                        )
                    )
                await self.db.flush()
                credited = True
        return credited

    async def beat(
        self,
        user: User,
        beat_id: uuid.UUID,
        client_id: uuid.UUID,
        was_active: bool,
        now_active: bool,
        study_view: bool,
        visible: bool,
    ) -> dict[str, Any]:
        await self._lock(user.id)
        now = activity.utcnow()
        fresh = await self.db.scalar(
            insert(StudyBeat)
            .values(user_id=user.id, beat_id=beat_id, received_at=now)
            .on_conflict_do_nothing()
            .returning(StudyBeat.beat_id)
        )
        if fresh is None:  # a retry or a replay: nothing changes
            await self.db.commit()
            return await self.state(user)
        await self._presence(user, now)
        row = await self._settle(await self._open(user.id), now)
        client = await self.db.get(StudyClient, (user.id, client_id))
        previous = (client.last_beat_at, client.last_beat_active) if client else None
        await self._observe(user.id, client_id, now, now_active and study_view and visible)
        if (
            row is not None
            and row.status == "active"
            and previous is not None
            and was_active
            and previous[1]
            and ZERO < now - previous[0] <= CREDIT_GAP
            and await self._credit(user.id, row.id, previous[0], now)
        ):
            row.alive_at = now
        await self.db.execute(
            delete(StudyClient).where(StudyClient.user_id == user.id, StudyClient.last_beat_at < now - KEEP_CLIENTS)
        )
        await self.db.execute(
            delete(StudyBeat).where(StudyBeat.user_id == user.id, StudyBeat.received_at < now - KEEP_CLIENTS)
        )
        await self.db.commit()
        return await self.state(user)

    # ---- summary (a read)
    async def summary(self, user: User, days: int) -> dict[str, Any]:
        now = activity.utcnow()
        zone = self._zone(user)
        today = activity.local_date(now, zone)
        first = today - timedelta(days=days - 1)
        # Wide enough for a session dated in another time zone than the student's current one.
        window_start = datetime.combine(first - timedelta(days=2), time(0), tzinfo=UTC)
        window_end = datetime.combine(today + timedelta(days=2), time(0), tzinfo=UTC)

        earliest = [
            await self.db.scalar(select(func.min(StudySession.started_at)).where(StudySession.user_id == user.id)),
            await self.db.scalar(select(func.min(AppSession.started_at)).where(AppSession.user_id == user.id)),
        ]
        known = [moment for moment in earliest if moment is not None]
        first_recorded = activity.local_date(min(known), zone) if known else None

        rows = list(
            await self.db.scalars(
                select(StudySession)
                .where(
                    StudySession.user_id == user.id,
                    StudySession.started_at < window_end,
                    (StudySession.ended_at.is_(None)) | (StudySession.ended_at > window_start),
                )
                .order_by(StudySession.started_at.desc())
            )
        )
        views = [SessionView(row, ending(row, now)) for row in rows]
        segments = await self._fill(views, now)
        latest_beat = await self._latest_beat(user.id)
        by_segment = {segment.id: segment for parts in segments.values() for segment in parts}
        intervals = (
            (
                await self.db.execute(
                    select(
                        StudyActiveInterval.segment_id, StudyActiveInterval.started_at, StudyActiveInterval.ended_at
                    ).where(StudyActiveInterval.segment_id.in_(list(by_segment)))
                )
            ).all()
            if by_segment
            else []
        )

        in_range = lambda day: first <= day <= today  # noqa: E731
        day_totals: dict[date, Totals] = defaultdict(Totals)
        app_time: dict[date, timedelta] = defaultdict(lambda: ZERO)
        subjects: dict[str | None, timedelta] = defaultdict(lambda: ZERO)
        chapters: dict[tuple[str | None, str, str, str], timedelta] = defaultdict(lambda: ZERO)
        activities: dict[str, timedelta] = defaultdict(lambda: ZERO)
        counted: set[uuid.UUID] = set()
        for view in views:
            session_zone = activity.zone_for(view.row.timezone, self.default_timezone)
            for segment in segments.get(view.row.id, []):
                end = segment.ended_at or max(self._open_end(view, latest_beat, now), segment.started_at)
                for day, span in split_days(segment.started_at, end, session_zone):
                    if in_range(day):
                        counted.add(view.row.id)
                        if segment.kind == "study":
                            day_totals[day].studying += span
                        else:
                            day_totals[day].paused += span
        zones = {view.row.id: activity.zone_for(view.row.timezone, self.default_timezone) for view in views}
        for segment_id, start, end in intervals:
            segment = by_segment[segment_id]
            for day, span in split_days(start, end, zones[segment.session_id]):
                if in_range(day):
                    day_totals[day].active += span
                    subjects[segment.subject_code] += span
                    activities[segment.activity] += span
                    if segment.chapter_id:
                        chapters[
                            (segment.subject_code, segment.chapter_id, segment.book_id, segment.chapter_title)
                        ] += span

        for app in await self.db.scalars(
            select(AppSession).where(
                AppSession.user_id == user.id,
                AppSession.started_at < window_end,
                AppSession.last_seen_at > window_start,
            )
        ):
            app_zone = activity.zone_for(app.timezone, self.default_timezone)
            for day, span in split_days(app.started_at, app.last_seen_at, app_zone):
                if in_range(day):
                    app_time[day] += span

        listed = [first + timedelta(days=n) for n in range(days)]
        listed = [day for day in listed if first_recorded is not None and day >= first_recorded]
        day_out = []
        for day in listed:
            parts = day_totals[day].out()
            day_out.append(
                {
                    "date": day,
                    "active_seconds": parts["active_seconds"],
                    "idle_seconds": parts["idle_seconds"],
                    "paused_seconds": parts["paused_seconds"],
                    "app_seconds": seconds(app_time[day]),
                }
            )

        def ranked(items: dict, build) -> list[dict[str, Any]]:
            return [
                build(key, seconds(span))
                for key, span in sorted(items.items(), key=lambda kv: -kv[1])
                if span >= timedelta(seconds=1)
            ]

        recent = [view for view in views if view.row.id in counted][:RECENT_SESSIONS]
        return {
            "timezone": zone.key,
            "start": first,
            "end": today,
            "first_recorded_date": first_recorded,
            "totals": {
                "active_seconds": sum(day["active_seconds"] for day in day_out),
                "idle_seconds": sum(day["idle_seconds"] for day in day_out),
                "paused_seconds": sum(day["paused_seconds"] for day in day_out),
                "app_seconds": sum(day["app_seconds"] for day in day_out),
                "sessions": len(counted),
            },
            "days": day_out,
            "subjects": ranked(subjects, lambda key, s: {"subject": key, "active_seconds": s}),
            "chapters": ranked(
                chapters,
                lambda key, s: {
                    "subject": key[0],
                    "chapter_id": key[1],
                    "book_id": key[2],
                    "chapter_title": key[3],
                    "active_seconds": s,
                },
            ),
            "activities": ranked(activities, lambda key, s: {"activity": key, "active_seconds": s}),
            "sessions": [
                {
                    "id": view.row.id,
                    "status": view.status,
                    "end_reason": view.end_reason,
                    "started_at": view.row.started_at,
                    "ended_at": view.ended_at,
                    **view.totals.out(),
                    "subjects": _distinct(segment.subject_code for segment in segments.get(view.row.id, [])),
                    "chapters": [
                        title
                        for title in _distinct(segment.chapter_title for segment in segments.get(view.row.id, []))
                        if title
                    ],
                    "activities": _distinct(segment.activity for segment in segments.get(view.row.id, [])),
                }
                for view in recent
            ],
        }


def _distinct(values: Iterable[Any]) -> list[Any]:
    return list(dict.fromkeys(values))
