"""Study time: what is credited (and what never is), across tabs and devices; liveness; totals that
add up; retries; concurrency; days in the student's time zone; app sessions; isolation."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.progress import activity
from app.rag.ncert import NcertKnowledge
from app.ratelimit import SlidingWindowLimiter
from app.study.service import Chapters
from tests.conftest import register

T0 = datetime(2026, 10, 15, 4, 0, 0, tzinfo=UTC)  # 09:30 in India


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def at(self, seconds: float, base: datetime = T0) -> None:
        self.moment = base + timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch, app) -> Clock:
    fixed = Clock(T0)
    monkeypatch.setattr(activity, "utcnow", fixed)
    # Simulated time passes instantly; the real limits are tested on their own.
    app.state.study_beat_limiter = SlidingWindowLimiter(limit=100_000, window_s=60)
    app.state.study_action_limiter = SlidingWindowLimiter(limit=100_000, window_s=60)
    return fixed


class Student:
    def __init__(self, client, headers) -> None:
        self.client = client
        self.headers = headers
        self.last: dict = {}

    async def _ok(self, response) -> dict:
        assert response.status_code == 200, response.text
        self.last = response.json()
        return self.last

    async def start(self, client_id, **context) -> dict:
        body = {"clientId": str(client_id), "activity": "reading", **context}
        return await self._ok(await self.client.post("/v1/study/session", json=body, headers=self.headers))

    async def beat(self, client_id, was: bool, now: bool | None = None, *, view=True, visible=True, beat_id=None):
        body = {
            "beatId": str(beat_id or uuid.uuid4()),
            "clientId": str(client_id),
            "wasActive": was,
            "nowActive": was if now is None else now,
            "studyView": view,
            "visible": visible,
        }
        return await self._ok(await self.client.post("/v1/study/beat", json=body, headers=self.headers))

    async def act(self, action: str, client_id, expected=None) -> httpx.Response:
        session = (await self.state())["session"]
        body = {"clientId": str(client_id), "expectedSegmentId": expected or session["segment"]["id"]}
        return await self.client.post(f"/v1/study/session/{session['id']}/{action}", json=body, headers=self.headers)

    async def state(self) -> dict:
        return await self._ok(await self.client.get("/v1/study/session", headers=self.headers))

    async def summary(self, days: int = 1) -> dict:
        response = await self.client.get("/v1/study/summary", params={"days": days}, headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()


async def _student(client, app) -> Student:
    account = await register(client, app)
    return Student(client, account["headers"])


def _active(state: dict) -> int:
    session = state["session"] or state["lastEnded"]
    return session["activeSeconds"]


def _reconciles(session: dict) -> bool:
    parts = session["activeSeconds"] + session["idleSeconds"] + session["pausedSeconds"]
    return parts == session["durationSeconds"] and min(session["idleSeconds"], session["activeSeconds"]) >= 0


async def _overlaps(app) -> int:
    async with app.state.db.sessionmaker() as db:
        return await db.scalar(
            text(
                "select count(*) from study_active_intervals a join study_active_intervals b "
                "on a.user_id = b.user_id and a.id < b.id "
                "and tstzrange(a.started_at, a.ended_at) && tstzrange(b.started_at, b.ended_at)"
            )
        )


async def test_one_client_credits_only_between_close_active_observations(client, app, clock):
    me, tab = await _student(client, app), uuid.uuid4()
    await me.start(tab)
    for second in (30, 60):
        clock.at(second)
        await me.beat(tab, True)
    assert _active(me.last) == 60
    clock.at(150)  # 90 s since the last beat: the whole span is uncredited
    await me.beat(tab, True)
    assert _active(me.last) == 60
    clock.at(180)  # the run resumes from 150
    await me.beat(tab, True)
    assert _active(me.last) == 90
    assert _reconciles(me.last["session"])


async def test_inactive_or_hidden_time_is_never_credited(client, app, clock):
    me, tab = await _student(client, app), uuid.uuid4()
    await me.start(tab)
    clock.at(20)
    await me.beat(tab, True, now=False)  # the edge: active until now, idle from now
    clock.at(50)
    await me.beat(tab, False)
    clock.at(60)
    await me.beat(tab, False, now=True)  # back: it *was* inactive, so nothing yet
    clock.at(90)
    await me.beat(tab, True)
    assert _active(me.last) == 50
    clock.at(100)
    await me.beat(tab, True, now=True, visible=False)  # hidden now: stored as inactive whatever it claims
    clock.at(130)
    await me.beat(tab, True)  # claims a run the server never saw start
    assert _active(me.last) == 60


async def test_union_of_two_clients_overlapping_and_gap_filling_counts_once(client, app, clock):
    me, a, b = await _student(client, app), uuid.uuid4(), uuid.uuid4()
    await me.start(a)
    clock.at(5)
    await me.beat(b, False, now=True)
    for second, tab in ((30, a), (35, b), (60, a), (65, b)):
        clock.at(second)
        await me.beat(tab, True)
    assert _active(me.last) == 65  # [0, 65): the union, not 60 + 60
    clock.at(70)
    await me.beat(a, True, now=False)
    clock.at(95)
    await me.beat(b, True)
    assert _active(me.last) == 95
    assert await _overlaps(app) == 0


async def test_one_client_active_while_another_idle_and_then_all_idle(client, app, clock):
    me, a, b = await _student(client, app), uuid.uuid4(), uuid.uuid4()
    await me.start(a)
    await me.beat(b, False)
    for second in (30, 60):
        clock.at(second)
        await me.beat(a, True)
        await me.beat(b, False)
    assert _active(me.last) == 60
    clock.at(70)
    await me.beat(a, True, now=False)
    for second in (100, 130):
        clock.at(second)
        await me.beat(a, False)
        await me.beat(b, False)
    assert _active(me.last) == 70


async def test_studying_moves_between_devices(client, app, clock):
    me, phone, laptop = await _student(client, app), uuid.uuid4(), uuid.uuid4()
    await me.start(phone)
    clock.at(30)
    await me.beat(phone, True)
    clock.at(40)
    await me.beat(phone, True, now=False)
    clock.at(45)
    await me.beat(laptop, False, now=True)
    clock.at(75)
    await me.beat(laptop, True)
    clock.at(80)
    await me.beat(phone, False)
    assert _active(me.last) == 70  # [0, 40) on the phone, [45, 75) on the laptop


async def test_presence_beats_never_keep_a_study_session_alive(client, app, clock):
    me, tab = await _student(client, app), uuid.uuid4()
    await me.start(tab)
    clock.at(30)
    await me.beat(tab, True, now=False)
    second = 60
    while second <= 17 * 60:  # Settings open, visible: presence, never study
        clock.at(second)
        await me.beat(tab, False, view=False)
        second += 30
    state = await me.state()
    assert state["session"] is None
    ended = state["lastEnded"]
    assert (ended["endReason"], ended["endedAt"]) == (
        "stale",
        (T0 + timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
    )
    assert (ended["activeSeconds"], ended["durationSeconds"]) == (30, 30) and _reconciles(ended)
    summary = await me.summary()
    assert summary["totals"]["appSeconds"] == 17 * 60 - 30  # open from the first beat (30 s) on


async def test_credit_never_enters_paused_or_ended_time_and_the_database_refuses_it(client, app, clock):
    me, tab = await _student(client, app), uuid.uuid4()
    await me.start(tab)
    clock.at(30)
    await me.beat(tab, True)
    clock.at(40)
    await me.beat(tab, True, now=False)
    assert (await me.act("pause", tab)).status_code == 200
    clock.at(50)
    await me.beat(tab, False, now=True)  # another tab that hasn't heard of the pause
    clock.at(70)
    await me.beat(tab, True)
    assert _active(me.last) == 40
    clock.at(100)
    assert (await me.act("resume", tab)).status_code == 200
    clock.at(130)
    await me.beat(tab, True)
    clock.at(140)
    await me.beat(tab, True, now=False)
    assert (await me.act("end", tab)).status_code == 200
    clock.at(170)
    await me.beat(tab, True)
    ended = (await me.state())["lastEnded"]
    assert (ended["activeSeconds"], ended["pausedSeconds"], ended["durationSeconds"], ended["idleSeconds"]) == (
        80,
        60,
        140,
        0,
    )

    async with app.state.db.sessionmaker() as db:
        paused = await db.scalar(text("select id from study_segments where kind = 'paused'"))
        studying = await db.scalar(text("select id from study_segments where kind = 'study' order by started_at"))
        user_id = await db.scalar(text("select user_id from study_segments limit 1"))
    bad = [
        ("paused", paused, T0 + timedelta(seconds=41), T0 + timedelta(seconds=42)),  # into a paused segment
        ("study", studying, T0 + timedelta(seconds=300), T0 + timedelta(seconds=301)),  # outside its segment
    ]
    for kind, segment, start, end in bad:
        with pytest.raises(DBAPIError):
            async with app.state.db.sessionmaker() as db:
                await db.execute(
                    text(
                        "insert into study_active_intervals (segment_id, user_id, segment_kind, started_at, ended_at) "
                        "values (:s, :u, :k, :a, :b)"
                    ),
                    {"s": segment, "u": user_id, "k": kind, "a": start, "b": end},
                )
                await db.commit()


async def test_totals_reconcile_in_every_ending(client, app, clock):
    # Paused too long: ends 60 minutes after the pause.
    me, tab = await _student(client, app), uuid.uuid4()
    await me.start(tab)
    clock.at(30)
    await me.beat(tab, True, now=False)
    await me.act("pause", tab)
    clock.at(30 + 61 * 60)
    ended = (await me.state())["lastEnded"]
    assert (ended["endReason"], ended["pausedSeconds"], ended["activeSeconds"]) == ("stale", 3600, 30)
    assert _reconciles(ended)

    # Eight hours, kept alive by study actions only: ends at the limit.
    other, tab = await _student(client, app), uuid.uuid4()
    base = T0 + timedelta(days=1)
    clock.at(0, base)
    await other.start(tab)
    for minute in range(14, 8 * 60, 14):
        clock.at(minute * 60, base)
        activity_name = "practice" if minute % 28 else "reading"
        session = (await other.state())["session"]
        response = await client.patch(
            f"/v1/study/session/{session['id']}",
            json={"clientId": str(tab), "expectedSegmentId": session["segment"]["id"], "activity": activity_name},
            headers=other.headers,
        )
        assert response.status_code == 200, response.text
    clock.at(8 * 3600 + 60, base)
    ended = (await other.state())["lastEnded"]
    assert (ended["endReason"], ended["durationSeconds"]) == ("limit", 8 * 3600) and _reconciles(ended)

    # Ended by the student, with two tabs: the summary's parts add up too.
    summary = await me.summary(days=2)
    for day in summary["days"]:
        assert day["activeSeconds"] >= 0 and day["idleSeconds"] >= 0


async def test_a_repeated_beat_and_lost_beats(client, app, clock):
    me, tab = await _student(client, app), uuid.uuid4()
    await me.start(tab)
    once = uuid.uuid4()
    clock.at(30)
    await me.beat(tab, True, beat_id=once)
    clock.at(31)
    await me.beat(tab, True, beat_id=once)  # the retry of a beat whose answer was lost: nothing changes
    clock.at(60)
    await me.beat(tab, True)
    assert _active(me.last) == 60  # [30, 60), not [31, 60)
    clock.at(120)  # one beat lost (90): costs nothing
    await me.beat(tab, True)
    assert _active(me.last) == 120
    clock.at(210)  # two lost (150, 180): that span is lost
    await me.beat(tab, True)
    assert _active(me.last) == 120
    clock.at(240)
    await me.beat(tab, True)
    assert _active(me.last) == 150


async def test_concurrent_starts_transitions_and_beats_converge(client, app, clock):
    me = await _student(client, app)
    tabs = [uuid.uuid4() for _ in range(5)]
    started = await asyncio.gather(*(me.start(tab) for tab in tabs))
    assert len({state["session"]["id"] for state in started}) == 1
    clock.at(30)
    await asyncio.gather(*(me.beat(tab, True) for tab in tabs))
    session = (await me.state())["session"]
    clock.at(40)
    results = await asyncio.gather(
        *(
            client.post(
                f"/v1/study/session/{session['id']}/{action}",
                json={"clientId": str(tab), "expectedSegmentId": session["segment"]["id"]},
                headers=me.headers,
            )
            for action, tab in (("pause", tabs[0]), ("pause", tabs[1]), ("end", tabs[2]))
        ),
        *(me.beat(tab, True) for tab in tabs[3:]),
    )
    codes = [result.status_code for result in results[:3]]
    assert set(codes) <= {200, 409} and 200 in codes
    state = await me.state()
    final = state["session"] or state["lastEnded"]
    assert _reconciles(final) and final["activeSeconds"] <= 40
    assert await _overlaps(app) == 0
    async with app.state.db.sessionmaker() as db:
        assert await db.scalar(text("select count(*) from study_sessions where ended_at is null")) <= 1
        assert await db.scalar(text("select count(*) from study_segments where ended_at is null")) <= 1


async def test_days_split_at_local_midnight_including_a_dst_change(client, app, clock):
    me, tab = await _student(client, app), uuid.uuid4()
    midnight = datetime(2026, 10, 15, 18, 30, tzinfo=UTC)  # 00:00 in India
    clock.at(-10, midnight)
    await me.start(tab)
    clock.at(20, midnight)
    await me.beat(tab, True)
    days = {day["date"]: day["activeSeconds"] for day in (await me.summary(days=2))["days"]}
    assert days == {"2026-10-15": 10, "2026-10-16": 20}

    other, tab = await _student(client, app), uuid.uuid4()
    me_ = (await client.get("/v1/me", headers=other.headers)).json()
    response = await client.patch(
        "/v1/me/profile",
        json={"version": me_["profileVersion"], "set": {"timezone": "America/New_York"}},
        headers=other.headers,
    )
    assert response.status_code == 200, response.text
    # 1 November 2026 has 25 hours in New York: its midnight after is 05:00 UTC, not 04:00.
    est_midnight = datetime(2026, 11, 2, 5, 0, tzinfo=UTC)
    clock.at(-10, est_midnight)
    await other.start(tab)
    clock.at(20, est_midnight)
    await other.beat(tab, True)
    days = {day["date"]: day["activeSeconds"] for day in (await other.summary(days=2))["days"]}
    assert days == {"2026-11-01": 10, "2026-11-02": 20}


async def test_app_sessions_are_a_union_and_a_gap_over_three_minutes_starts_another(client, app, clock):
    me, a, b = await _student(client, app), uuid.uuid4(), uuid.uuid4()
    for second, tab in ((0, a), (10, b), (30, a), (40, b), (60, a)):
        clock.at(second)
        await me.beat(tab, False, view=False)
    for second in (241, 270, 300):
        clock.at(second)
        await me.beat(a, False, visible=False)
    assert (await me.summary())["totals"]["appSeconds"] == 60 + 59
    async with app.state.db.sessionmaker() as db:
        assert await db.scalar(text("select count(*) from app_sessions")) == 2


async def test_reads_never_write(client, app, clock):
    me, tab = await _student(client, app), uuid.uuid4()
    await me.start(tab)
    clock.at(30)
    await me.beat(tab, True)
    clock.at(30 + 16 * 60)

    async def snapshot() -> list:
        async with app.state.db.sessionmaker() as db:
            tables = ("study_sessions", "study_segments", "study_active_intervals", "study_clients", "study_beats")
            return [
                sorted(map(tuple, (await db.execute(text(f"select * from {table}"))).all()), key=str)
                for table in (*tables, "app_sessions")
            ]

    before = await snapshot()
    state = await me.state()
    await me.summary(days=7)
    await client.get("/v1/study/chapters", params={"subject": "science"}, headers=me.headers)
    assert state["session"] is None and state["lastEnded"]["endReason"] == "stale"
    assert await snapshot() == before


def _ncert(handler) -> Chapters:
    return Chapters(
        NcertKnowledge("http://127.0.0.1:4200", "ncertkb_test", 2.0, transport=httpx.MockTransport(handler))
    )


async def test_isolation_validation_limits_and_chapters(client, app, clock):
    me, other, tab = await _student(client, app), await _student(client, app), uuid.uuid4()
    await me.start(tab)
    clock.at(30)
    await me.beat(tab, True)
    session = (await me.state())["session"]
    body = {"clientId": str(tab), "expectedSegmentId": session["segment"]["id"]}
    for action in ("pause", "resume", "end"):
        response = await client.post(f"/v1/study/session/{session['id']}/{action}", json=body, headers=other.headers)
        assert response.status_code == 404
    response = await client.patch(
        f"/v1/study/session/{session['id']}", json={**body, "activity": "test"}, headers=other.headers
    )
    assert response.status_code == 404
    assert (await other.state())["session"] is None
    assert (await other.summary(days=7))["totals"]["activeSeconds"] == 0
    assert (await me.summary(days=7))["totals"]["activeSeconds"] == 30

    beat = {"beatId": str(uuid.uuid4()), "clientId": str(tab), "wasActive": True, "nowActive": True}
    for extra in ({"durationSeconds": 3600}, {"userId": str(uuid.uuid4())}):
        response = await client.post(
            "/v1/study/beat", json={**beat, "studyView": True, "visible": True, **extra}, headers=me.headers
        )
        assert response.status_code == 422
    assert (
        await client.post("/v1/study/session", json={"clientId": str(tab), "subject": "alchemy"}, headers=me.headers)
    ).status_code == 422

    app.state.study_beat_limiter = SlidingWindowLimiter(limit=2, window_s=60)
    codes = [
        (
            await client.post(
                "/v1/study/beat",
                json={**beat, "beatId": str(uuid.uuid4()), "studyView": True, "visible": True},
                headers=me.headers,
            )
        ).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]

    # Chapters: the student's class, the service's titles; a wrong chapter is refused.
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "chapter_id": "sci-8-en-ch01",
                        "book_id": "sci-8-en",
                        "ordinal": 1,
                        "number": 1,
                        "title": "Crop Production",
                    },
                    {
                        "chapter_id": "sci-8-en-ch02",
                        "book_id": "sci-8-en",
                        "ordinal": 2,
                        "number": 2,
                        "title": "Microorganisms",
                    },
                ],
                "next_cursor": None,
                "meta": {},
            },
        )

    app.state.study_chapters = _ncert(handler)
    response = await client.get("/v1/study/chapters", params={"subject": "science"}, headers=other.headers)
    assert response.json() == {"available": False, "reason": "no_class", "chapters": []}
    learning = await client.patch(
        "/v1/learning/profile", json={"version": 0, "set": {"grade": "class_8"}}, headers=other.headers
    )
    assert learning.status_code == 200, learning.text
    response = await client.get("/v1/study/chapters", params={"subject": "science"}, headers=other.headers)
    assert response.json()["available"] and [c["title"] for c in response.json()["chapters"]] == [
        "Crop Production",
        "Microorganisms",
    ]
    assert asked[-1] == {"classes": "8", "subjects": "science", "languages": "en", "limit": "500"}
    started = await other.start(uuid.uuid4(), subject="science", chapterId="sci-8-en-ch02")
    assert started["session"]["segment"]["chapterTitle"] == "Microorganisms"
    response = await client.post(
        "/v1/study/session",
        json={"clientId": str(uuid.uuid4()), "subject": "science", "chapterId": "made-up"},
        headers=other.headers,
    )
    assert response.status_code == 422  # checked before joining the open session

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    app.state.study_chapters = _ncert(down)
    response = await client.get("/v1/study/chapters", params={"subject": "mathematics"}, headers=other.headers)
    assert response.json() == {"available": False, "reason": "unavailable", "chapters": []}
    session = (await other.state())["session"]
    response = await client.patch(
        f"/v1/study/session/{session['id']}",
        json={
            "clientId": str(tab),
            "expectedSegmentId": session["segment"]["id"],
            "subject": "mathematics",
            "chapterId": "math-8-en-ch01",
        },
        headers=other.headers,
    )
    assert response.status_code == 503
