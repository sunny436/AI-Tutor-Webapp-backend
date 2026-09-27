"""The learning streak and the in-app notifications.

Meaningful, fully answered questions only; India days; one row per day however it is sent;
the streak derived from the days; milestones once; the evening reminder once a day and never
after learning; the bell's list bounded and per user.
"""

import asyncio
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.llm.base import LLMError
from app.progress import activity
from app.progress.learning import day_end, intensity, is_meaningful, learning_date
from tests.conftest import PASSWORD, register, stream_chat

QUESTION = "Explain photosynthesis in simple words"
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def ist(self, text_: str) -> None:
        """Set the clock to a moment in India time."""
        self.moment = datetime.fromisoformat(text_ + "+05:30").astimezone(UTC)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    fixed = Clock(datetime(2026, 9, 26, 6, 0, tzinfo=UTC))  # 11:30 IST
    monkeypatch.setattr(activity, "utcnow", fixed)
    return fixed


async def sql(database: str, statement: str, **params) -> list[dict]:
    engine = create_async_engine(database)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(statement), params)
            return [dict(row) for row in result.mappings().all()] if result.returns_rows else []
    finally:
        await engine.dispose()


async def learned_on(database: str, account: dict, *days: date) -> None:
    for day in days:
        await sql(
            database,
            "INSERT INTO learning_daily_activity (user_id, activity_date) VALUES (:id, :day)",
            id=uuid.UUID(account["user"]["id"]),
            day=day,
        )


async def ask(client, headers, message: str = QUESTION) -> list:
    response, events = await stream_chat(client, headers, message)
    assert response.status_code == 200, response.text
    return events


async def streak(client, headers) -> dict:
    response = await client.get("/v1/progress/streak", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def inbox(client, headers, query: str = "") -> dict:
    response = await client.get(f"/v1/notifications{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ----------------------------------------------------------------------- rules
def test_what_counts_as_meaningful():
    for text_ in ("hi", "Hello!", "thanks", "ok", "hello how are you", "hi sir", "   ", "", "2+2", "k"):
        assert not is_meaningful(text_), text_
    for text_ in (QUESTION, "What is 12 x 15?", "photosynthesis", "Explain Newton's laws", "प्रकाश संश्लेषण क्या है"):
        assert is_meaningful(text_), text_


def test_india_dates_and_the_end_of_the_day():
    at = lambda s: datetime.fromisoformat(s + "+05:30")  # noqa: E731
    assert learning_date(at("2026-09-26T23:59")) == date(2026, 9, 26)
    assert learning_date(at("2026-09-27T00:00")) == date(2026, 9, 27)
    assert learning_date(datetime(2026, 9, 26, 18, 31, tzinfo=UTC)) == date(2026, 9, 27)  # 00:01 IST
    assert day_end(at("2026-09-26T21:46")) == at("2026-09-27T00:00")
    assert day_end(at("2026-12-31T12:00")) == at("2027-01-01T00:00")


def test_calendar_intensity_levels():
    assert [intensity(n) for n in (1, 2, 3, 5, 6, 9, 10, 40)] == [1, 1, 2, 2, 3, 3, 4, 4]


# ---------------------------------------------------------------------- streak
async def test_first_learning_day_and_today_status(client, app, clock):
    headers = (await register(client, app))["headers"]
    before = await streak(client, headers)
    assert before == {
        "currentStreak": 0,
        "longestStreak": 0,
        "todayActive": False,
        "todayDate": "2026-09-26",
        "timezone": "Asia/Kolkata",
        "dayEnd": "2026-09-26T18:30:00Z",
    }
    await ask(client, headers)
    after = await streak(client, headers)
    assert (after["currentStreak"], after["longestStreak"], after["todayActive"]) == (1, 1, True)


async def test_small_talk_and_failed_replies_do_not_count(client, app, clock, fake_llm):
    headers = (await register(client, app))["headers"]
    await ask(client, headers, "hi")
    await ask(client, headers, "thanks")
    fake_llm.fail_before_first = LLMError("down")
    await ask(client, headers, QUESTION)
    assert (await streak(client, headers))["currentStreak"] == 0


async def test_a_regenerated_answer_does_not_count_again(client, app, clock, database):
    account = await register(client, app)
    events = await ask(client, account["headers"])
    conversation = next(data["conversationId"] for name, data in events if name == "meta")
    response = await client.post(f"/v1/conversations/{conversation}/regenerate/stream", headers=account["headers"])
    assert response.status_code == 200
    rows = await sql(database, "SELECT interactions FROM learning_daily_activity")
    assert rows == [{"interactions": 1}]


async def test_many_questions_a_day_and_parallel_sends_make_one_day(client, app, clock, database):
    headers = (await register(client, app))["headers"]
    await ask(client, headers)
    await asyncio.gather(*(ask(client, headers, f"{QUESTION} number {n}") for n in range(3)))
    rows = await sql(database, "SELECT activity_date, interactions FROM learning_daily_activity")
    assert rows == [{"activity_date": date(2026, 9, 26), "interactions": 4}]
    days = (await client.get("/v1/progress/learning-days", headers=headers)).json()
    assert days["days"] == [{"date": "2026-09-26", "interactions": 4, "intensity": 2}]


async def test_consecutive_days_across_month_and_year_boundaries(client, app, clock):
    headers = (await register(client, app))["headers"]
    for moment in ("2026-12-30T10:00", "2026-12-31T23:59", "2027-01-01T00:00", "2027-01-02T09:00"):
        clock.ist(moment)
        await ask(client, headers)
    assert (await streak(client, headers))["currentStreak"] == 4


async def test_the_india_midnight_boundary(client, app, clock, database):
    headers = (await register(client, app))["headers"]
    clock.ist("2026-09-26T23:59")
    await ask(client, headers)
    clock.ist("2026-09-27T00:00")
    await ask(client, headers)
    rows = await sql(database, "SELECT activity_date FROM learning_daily_activity ORDER BY activity_date")
    assert [row["activity_date"] for row in rows] == [date(2026, 9, 26), date(2026, 9, 27)]
    assert (await streak(client, headers))["currentStreak"] == 2


async def test_pending_today_then_broken_then_resumed_and_the_longest(client, app, clock, database):
    account = await register(client, app)
    headers = account["headers"]
    await learned_on(database, account, date(2026, 9, 20), date(2026, 9, 21), date(2026, 9, 22))
    clock.ist("2026-09-22T20:00")
    assert (await streak(client, headers))["currentStreak"] == 3
    clock.ist("2026-09-23T10:00")  # nothing yet today: still 3, today pending
    state = await streak(client, headers)
    assert (state["currentStreak"], state["todayActive"]) == (3, False)
    clock.ist("2026-09-24T00:00")  # the 23rd ended without learning: broken
    assert (await streak(client, headers))["currentStreak"] == 0
    clock.ist("2026-09-24T09:00")
    await ask(client, headers)  # resumed
    state = await streak(client, headers)
    assert (state["currentStreak"], state["longestStreak"], state["todayActive"]) == (1, 3, True)
    progress = (await client.get("/v1/progress", headers=headers)).json()
    assert progress["streak"] == {"currentDays": 1, "longestDays": 3}  # one streak everywhere


async def test_the_calendar_range_is_bounded(client, app, clock):
    headers = (await register(client, app))["headers"]
    ok = await client.get("/v1/progress/learning-days?from=2025-09-27&to=2026-09-26", headers=headers)
    assert ok.status_code == 200 and ok.json()["days"] == []
    for query in ("from=2026-09-26&to=2026-09-01", "from=2024-01-01&to=2026-09-26"):
        assert (await client.get(f"/v1/progress/learning-days?{query}", headers=headers)).status_code == 422


# ------------------------------------------------------------------ milestones
async def test_a_milestone_is_announced_once(client, app, clock, database):
    account = await register(client, app)
    headers = account["headers"]
    await learned_on(database, account, date(2026, 9, 24), date(2026, 9, 25))
    await ask(client, headers)  # the third day
    await ask(client, headers)  # again the same day
    milestones = [item for item in (await inbox(client, headers))["items"] if item["kind"] == "streak_milestone"]
    assert [(item["title"], item["body"]) for item in milestones] == [
        ("🔥 3 Day Streak!", "You've learned for 3 days in a row.")
    ]
    # Broken, then three days again: the 3-day milestone is not announced a second time.
    await sql(database, "DELETE FROM learning_daily_activity")
    await learned_on(database, account, date(2026, 9, 24), date(2026, 9, 25))
    await ask(client, headers)
    kinds = [item["kind"] for item in (await inbox(client, headers))["items"]]
    assert kinds.count("streak_milestone") == 1


# ------------------------------------------------------------------- reminders
async def test_the_evening_reminder_comes_once_and_never_after_learning(client, app, clock, database):
    account = await register(client, app)
    headers = account["headers"]
    await learned_on(database, account, date(2026, 9, 25))
    clock.ist("2026-09-26T17:59")
    assert (await inbox(client, headers))["items"] == []  # too early
    clock.ist("2026-09-26T18:30")
    first = (await inbox(client, headers))["items"]
    assert [(item["kind"], item["title"]) for item in first] == [("streak_reminder", "🔥 Your 1-day streak is waiting")]
    assert "5h 30m left today" in first[0]["body"]
    clock.ist("2026-09-26T21:00")
    assert len((await inbox(client, headers))["items"]) == 1  # once a day

    other = await register(client, app)
    await learned_on(database, other, date(2026, 9, 25))
    clock.ist("2026-09-26T10:00")
    await ask(client, other["headers"])  # learnt today
    clock.ist("2026-09-26T19:00")
    assert (await inbox(client, other["headers"]))["items"] == []


async def test_no_reminder_when_turned_off_or_never_learnt(client, app, clock, database):
    new = await register(client, app)
    clock.ist("2026-09-26T19:00")
    assert (await inbox(client, new["headers"]))["items"] == []  # never learnt
    account = await register(client, app)
    await learned_on(database, account, date(2026, 9, 25))
    off = await client.patch(
        "/v1/notifications/preferences",
        json={"version": 0, "set": {"inAppReminders": False}},
        headers=account["headers"],
    )
    assert off.status_code == 200 and off.json()["inAppReminders"] is False
    assert (await client.get("/v1/notifications/preferences", headers=account["headers"])).json()[
        "inAppReminders"
    ] is False
    assert (await inbox(client, account["headers"]))["items"] == []


# ------------------------------------------------------------------- the bell
async def test_the_list_never_exceeds_thirty(client, app, clock, database):
    account = await register(client, app)
    for n in range(35):
        await sql(
            database,
            "INSERT INTO user_notifications (user_id, kind, title, body, dedup_key) "
            "VALUES (:id, 'streak_milestone', 'T', 'B', :key)",
            id=uuid.UUID(account["user"]["id"]),
            key=f"k{n}",
        )
    listed = await inbox(client, account["headers"])
    assert len(listed["items"]) == 30 and listed["unreadCount"] == 35
    assert len((await inbox(client, account["headers"], "?limit=5"))["items"]) == 5
    for bad in ("?limit=1000", "?limit=0", "?limit=31"):
        assert (await client.get(f"/v1/notifications{bad}", headers=account["headers"])).status_code == 422


async def test_marking_read_and_other_students_notifications(client, app, clock, database):
    alice = await register(client, app)
    bob = await register(client, app)
    for account, key in ((alice, "a1"), (alice, "a2"), (bob, "b1")):
        await sql(
            database,
            "INSERT INTO user_notifications (user_id, kind, title, body, dedup_key) "
            "VALUES (:id, 'streak_milestone', 'T', 'B', :key)",
            id=uuid.UUID(account["user"]["id"]),
            key=key,
        )
    alice_items = (await inbox(client, alice["headers"]))["items"]
    bob_items = (await inbox(client, bob["headers"]))["items"]
    assert len(alice_items) == 2 and len(bob_items) == 1  # each sees only their own
    # Bob names Alice's notification: nothing of hers changes.
    marked = await client.post("/v1/notifications/read", json={"ids": [alice_items[0]["id"]]}, headers=bob["headers"])
    assert marked.status_code == 204
    assert (await inbox(client, alice["headers"]))["unreadCount"] == 2
    await client.post("/v1/notifications/read", json={"ids": [alice_items[0]["id"]]}, headers=alice["headers"])
    assert (await inbox(client, alice["headers"]))["unreadCount"] == 1
    await client.post("/v1/notifications/read", json={}, headers=alice["headers"])
    assert (await inbox(client, alice["headers"]))["unreadCount"] == 0
    assert (await inbox(client, bob["headers"]))["unreadCount"] == 1


async def test_each_student_sees_only_their_own_streak_and_days(client, app, clock):
    alice = await register(client, app)
    bob = await register(client, app)
    await ask(client, alice["headers"])
    assert (await streak(client, bob["headers"]))["currentStreak"] == 0
    assert (await client.get("/v1/progress/learning-days", headers=bob["headers"])).json()["days"] == []
    # Nothing about the streak can be set: there is no write endpoint, and unknown fields are refused.
    assert (
        await client.post("/v1/progress/streak", json={"currentStreak": 99}, headers=bob["headers"])
    ).status_code == 405


async def test_security_alerts_also_appear_in_the_bell(client, app, clock):
    account = await register(client, app)
    await client.post(
        "/v1/auth/login",
        json={"email": account["email"], "password": PASSWORD},
        headers={"User-Agent": IPHONE},
    )
    items = (await inbox(client, account["headers"]))["items"]
    assert [item["kind"] for item in items] == ["security_sign_in"]
    assert "Safari on iPhone" in items[0]["body"] and "127.0.0" not in items[0]["body"]
    assert items[0]["link"] == "/settings/privacy"
