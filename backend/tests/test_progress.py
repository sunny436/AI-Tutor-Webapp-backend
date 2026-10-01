"""Progress: active minutes (deduplicated), questions, the student's own days, streaks, goals."""

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from app.progress import activity
from app.progress.activity import streaks
from app.ratelimit import SlidingWindowLimiter
from tests.conftest import make_settings, register, sign_in, stream_chat


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def set(self, text: str) -> None:
        self.moment = datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch, app) -> Clock:
    fixed = Clock(datetime(2026, 9, 25, 6, 0, 10, tzinfo=UTC))
    monkeypatch.setattr(activity, "utcnow", fixed)
    # Simulated minutes pass instantly; the real per-minute limit is tested on its own.
    app.state.activity_limiter = SlidingWindowLimiter(limit=1000, window_s=60)
    return fixed


async def _beat(client, headers) -> dict:
    response = await client.post("/v1/progress/activity", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _progress(client, headers, days: int = 7) -> dict:
    response = await client.get(f"/v1/progress?days={days}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- active minutes
async def test_a_minute_is_credited_once(client, app, clock):
    headers = (await register(client, app))["headers"]
    assert await _beat(client, headers) == {"credited": True, "date": "2026-09-25"}
    clock.set("2026-09-25T06:00:50")
    assert (await _beat(client, headers))["credited"] is False  # the same UTC minute
    clock.set("2026-09-25T06:01:00")
    assert (await _beat(client, headers))["credited"] is True
    assert (await _progress(client, headers))["today"] == {"date": "2026-09-25", "activeMinutes": 2, "questions": 0}


async def test_two_devices_reporting_the_same_minute_count_it_once(client, app, clock):
    account = await register(client, app)
    phone = (await sign_in(app, account["email"]))["headers"]
    results = await asyncio.gather(*(_beat(client, headers) for headers in (account["headers"], phone) * 2))
    assert sorted(result["credited"] for result in results) == [False, False, False, True]
    assert (await _progress(client, phone))["today"]["activeMinutes"] == 1


async def test_reporting_activity_is_rate_limited(client, app, clock):
    headers = (await register(client, app))["headers"]
    app.state.activity_limiter = SlidingWindowLimiter(limit=2, window_s=60)
    await _beat(client, headers)
    await _beat(client, headers)
    refused = await client.post("/v1/progress/activity", headers=headers)
    assert refused.status_code == 429


# --------------------------------------------------------------------- questions
async def test_accepted_questions_are_counted_and_regenerations_are_not(client, app, clock):
    headers = (await register(client, app))["headers"]
    _, events = await stream_chat(client, headers, "What is a prime number?")
    await stream_chat(client, headers, "And a composite one?", events[0][1]["conversationId"])
    regenerate = await client.post(
        f"/v1/conversations/{events[0][1]['conversationId']}/regenerate/stream", headers=headers
    )
    assert regenerate.status_code == 200
    too_long = await client.post("/v1/chat/stream", json={"message": "x" * 16_001}, headers=headers)
    assert too_long.status_code == 422  # refused before it is accepted: not a question asked
    assert (await _progress(client, headers))["today"]["questions"] == 2


# ------------------------------------------------------------------ whose "today"
async def test_days_follow_the_default_time_zone_until_one_is_chosen(client, app, clock):
    headers = (await register(client, app))["headers"]
    clock.set("2026-09-25T18:29:30")  # 23:59:30 in India (DEFAULT_TIMEZONE)
    assert (await _beat(client, headers))["date"] == "2026-09-25"
    clock.set("2026-09-25T18:30:10")  # 00:00:10 the next day in India
    assert (await _beat(client, headers))["date"] == "2026-09-26"
    summary = await _progress(client, headers)
    assert (summary["timezone"], summary["timezoneIsDefault"]) == ("Asia/Kolkata", True)
    assert summary["today"]["date"] == "2026-09-26"
    assert [day["activeMinutes"] for day in summary["days"][-2:]] == [1, 1]


async def test_days_follow_the_students_time_zone_across_daylight_saving(client, app, clock):
    headers = (await register(client, app))["headers"]
    me = (await client.get("/v1/me", headers=headers)).json()
    await client.patch(
        "/v1/me/profile",
        json={"version": me["profileVersion"], "set": {"timezone": "America/New_York"}},
        headers=headers,
    )
    # New York moves its clocks forward at 02:00 on 8 March 2026 (07:00 UTC).
    for moment, expected in (
        ("2026-03-08T04:59:00", "2026-03-07"),  # 23:59 EST
        ("2026-03-08T05:00:00", "2026-03-08"),  # 00:00 EST
        ("2026-03-08T06:59:00", "2026-03-08"),  # 01:59 EST
        ("2026-03-08T07:00:00", "2026-03-08"),  # 03:00 EDT: still the same day
        ("2026-03-09T03:59:00", "2026-03-08"),  # 23:59 EDT
        ("2026-03-09T04:00:00", "2026-03-09"),  # 00:00 EDT
    ):
        clock.set(moment)
        assert (await _beat(client, headers))["date"] == expected, moment
    summary = await _progress(client, headers)
    assert (summary["timezone"], summary["timezoneIsDefault"]) == ("America/New_York", False)
    by_date = {day["date"]: day["activeMinutes"] for day in summary["days"]}
    assert (by_date["2026-03-07"], by_date["2026-03-08"], by_date["2026-03-09"]) == (1, 4, 1)


# ------------------------------------------------------------------------ streaks
def test_streak_arithmetic():
    today = date(2026, 9, 25)
    days = lambda *offsets: {today - timedelta(days=n) for n in offsets}  # noqa: E731
    assert streaks(set(), today) == (0, 0)
    assert streaks(days(0), today) == (1, 1)
    assert streaks(days(0, 1, 2), today) == (3, 3)
    assert streaks(days(1, 2), today) == (2, 2)  # today not active yet: the streak is still alive
    assert streaks(days(2, 3), today) == (0, 2)  # yesterday missed: broken
    assert streaks(days(0, 1, 5, 6, 7, 8), today) == (2, 4)
    assert streaks(days(0, 2), today) == (1, 1)


async def test_the_summary_counts_weeks_goals_and_the_streak(client, app, clock):
    headers = (await register(client, app))["headers"]
    await client.patch(
        "/v1/learning/profile",
        json={"version": 0, "set": {"dailyActiveMinutesGoal": 2, "weeklyActiveMinutesGoal": 5}},
        headers=headers,
    )
    # Monday 21 to Friday 25 September 2026 (India), each at 09:00 local.
    for day, minutes in ((21, 1), (22, 0), (23, 2), (24, 1), (25, 2)):
        for minute in range(minutes):
            clock.set(f"2026-09-{day:02d}T03:3{minute}:00")
            await _beat(client, headers)
    clock.set("2026-09-25T03:40:00")
    await stream_chat(client, headers, "Is 91 prime?")

    summary = await _progress(client, headers)
    assert summary["today"] == {"date": "2026-09-25", "activeMinutes": 2, "questions": 1}
    assert summary["thisWeek"] == {"startDate": "2026-09-21", "activeMinutes": 6, "questions": 1}
    # The learning streak: only the answered question counts (active minutes don't).
    assert summary["streak"] == {"currentDays": 1, "longestDays": 1}
    assert summary["goals"] == {
        "dailyActiveMinutes": 2,
        "weeklyActiveMinutes": 5,
        "dailyMet": True,
        "weeklyMet": True,
    }
    assert [day["date"] for day in summary["days"]] == [f"2026-09-{n}" for n in range(19, 26)]
    assert [day["activeMinutes"] for day in summary["days"]] == [0, 0, 1, 0, 2, 1, 2]


async def test_a_new_student_has_an_empty_summary(client, app, clock):
    headers = (await register(client, app))["headers"]
    summary = await _progress(client, headers, days=7)
    assert summary["today"] == {"date": "2026-09-25", "activeMinutes": 0, "questions": 0}
    assert summary["streak"] == {"currentDays": 0, "longestDays": 0}
    assert summary["goals"] == {
        "dailyActiveMinutes": None,
        "weeklyActiveMinutes": None,
        "dailyMet": None,
        "weeklyMet": None,
    }
    assert len(summary["days"]) == 7
    for days in (6, 91, "x"):
        assert (await client.get(f"/v1/progress?days={days}", headers=headers)).status_code == 422


def test_the_default_time_zone_must_be_real():
    assert make_settings(default_timezone="Europe/London").default_timezone == "Europe/London"
    with pytest.raises(ValueError):
        make_settings(default_timezone="Mars/Olympus")
