"""The jobs worker (app/jobs/runner.py): rollout modes, at-most-once sending, reminders, retention."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.emails import EmailDeliveryError
from app.jobs.runner import LOCK_KEY, run_once
from app.notifications.outbox import SECURITY_PASSWORD_CHANGED, SECURITY_SIGN_IN, queue_email
from tests.conftest import make_settings, register

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Safari/604.1"
APP_URL = "https://padhai.example"


def worker_settings(**overrides):
    values = {"jobs_enabled": True, "notifications_mode": "on", "public_app_url": APP_URL} | overrides
    return make_settings(**values)


async def run(app, now: datetime | None = None, **overrides) -> dict:
    return await run_once(worker_settings(**overrides), app.state.db, app.state.email_sender, now)


async def sql(database: str, statement: str, **params) -> list[dict]:
    engine = create_async_engine(database)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(statement), params)
            return [dict(row) for row in result.mappings().all()] if result.returns_rows else []
    finally:
        await engine.dispose()


def sent_to(app, address: str) -> list[dict]:
    return [mail for mail in app.state.email_sender.outbox if mail["to"] == address]


async def statuses(database: str, user_id: str) -> list[tuple[str, str]]:
    rows = await sql(
        database, "SELECT kind, status FROM email_outbox WHERE user_id = :id ORDER BY created_at", id=uuid.UUID(user_id)
    )
    return [(row["kind"], row["status"]) for row in rows]


async def queue_alert(app, account, kind: str = SECURITY_SIGN_IN) -> None:
    """An email waiting in the outbox for this student. (Security alerts are sent at once now;
    the worker still sends whatever is queued, such as reminders and summaries.)"""
    subject = {
        SECURITY_SIGN_IN: "New sign-in to your PadhAI account",
        SECURITY_PASSWORD_CHANGED: "Your PadhAI password was changed",
    }[kind]
    async with app.state.db.sessionmaker() as db:
        await queue_email(
            db,
            kind=kind,
            to=account["email"],
            subject=subject,
            body=f"{subject}.\n\n    Device: Safari on iPhone",
            send_before=datetime.now(UTC) + timedelta(days=1),
            user_id=uuid.UUID(account["user"]["id"]),
        )
        await db.commit()


# --------------------------------------------------------------------- the switch
async def test_a_disabled_worker_does_nothing(client, app, database):
    account = await register(client, app)
    await queue_alert(app, account)
    assert await run(app, jobs_enabled=False) == {"skipped": "JOBS_ENABLED is false"}
    assert await statuses(database, account["user"]["id"]) == [("security_sign_in", "pending")]
    assert sent_to(app, account["email"]) == []  # nothing sent


async def test_a_second_worker_finds_the_lock_taken(client, app, database):
    engine = create_async_engine(database)
    try:
        async with engine.connect() as holder:
            assert await holder.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})
            assert await run(app) == {"skipped": "another run holds the lock"}
            await holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
    finally:
        await engine.dispose()
    assert "send" in await run(app)


# ----------------------------------------------------------------- rollout modes
async def test_mode_off_sends_no_student_email(client, app, database):
    account = await register(client, app)
    await queue_alert(app, account)
    report = await run(app, notifications_mode="off")
    assert report["reminders"] == "off"
    assert await statuses(database, account["user"]["id"]) == [("security_sign_in", "pending")]


async def test_dry_run_records_what_would_be_sent(client, app, database):
    account = await register(client, app)
    await queue_alert(app, account)
    before = len(app.state.email_sender.outbox)
    await run(app, notifications_mode="dry_run")
    assert await statuses(database, account["user"]["id"]) == [("security_sign_in", "dry_run")]
    assert len(app.state.email_sender.outbox) == before


async def test_allowlist_sends_only_to_the_allowlisted(client, app, database):
    listed = await register(client, app)
    other = await register(client, app)
    for account in (listed, other):
        await queue_alert(app, account)
    await run(app, notifications_mode="allowlist", notifications_allowlist=f" {listed['email'].upper()} , x@y.z")
    assert await statuses(database, listed["user"]["id"]) == [("security_sign_in", "sent")]
    assert await statuses(database, other["user"]["id"]) == [("security_sign_in", "suppressed")]
    assert sent_to(app, listed["email"])[-1]["subject"].startswith("New sign-in")
    assert not [mail for mail in sent_to(app, other["email"]) if mail["subject"].startswith("New sign-in")]


async def test_on_sends_and_a_kind_outside_the_list_is_suppressed(client, app, database):
    account = await register(client, app)
    await queue_alert(app, account)
    await queue_alert(app, account, SECURITY_PASSWORD_CHANGED)
    await run(app, notifications_kinds="security_password_changed")
    assert await statuses(database, account["user"]["id"]) == [
        ("security_sign_in", "suppressed"),
        ("security_password_changed", "sent"),
    ]
    assert sent_to(app, account["email"])[-1]["subject"].endswith("password was changed")


async def test_notifications_without_a_public_address_stay_off(client, app, database):
    account = await register(client, app)
    await queue_alert(app, account)
    report = await run(app, public_app_url="")
    assert report["reminders"] == "off"
    assert await statuses(database, account["user"]["id"]) == [("security_sign_in", "pending")]


# -------------------------------------------------------------- at most once
async def test_stale_news_expires_instead_of_being_sent(client, app, database):
    account = await register(client, app)
    await queue_alert(app, account)
    await run(app, now=datetime.now(UTC) + timedelta(days=2))
    assert await statuses(database, account["user"]["id"]) == [("security_sign_in", "expired")]


async def test_a_row_left_sending_by_a_crash_is_never_sent_again(client, app, database):
    account = await register(client, app)
    await queue_alert(app, account)
    await sql(
        database,
        "UPDATE email_outbox SET status = 'sending', attempts = 1, claimed_at = now() - interval '10 minutes' "
        "WHERE user_id = :id",
        id=uuid.UUID(account["user"]["id"]),
    )
    before = len(app.state.email_sender.outbox)
    report = await run(app)
    assert report["recovered"] == 1
    assert await statuses(database, account["user"]["id"]) == [("security_sign_in", "unknown")]
    assert len(app.state.email_sender.outbox) == before


class FlakySender:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.attempts = 0

    async def send(self, to: str, subject: str, body: str, html: str | None = None) -> None:
        assert html is None  # the queued outbox intentionally stores text only
        self.attempts += 1
        raise self.error


async def test_a_refused_email_is_retried_with_backoff_then_fails(client, app, database):
    account = await register(client, app)
    await queue_alert(app, account)
    flaky = FlakySender(EmailDeliveryError("rejected (HTTP 500)"))
    now = datetime.now(UTC) + timedelta(seconds=5)
    settings = worker_settings()
    await run_once(settings, app.state.db, flaky, now)
    [row] = await sql(database, "SELECT status, attempts, next_attempt_at FROM email_outbox")
    assert (row["status"], row["attempts"]) == ("pending", 1)
    assert row["next_attempt_at"] >= now + timedelta(seconds=59)
    await run_once(settings, app.state.db, flaky, now + timedelta(seconds=30))  # not due yet
    assert flaky.attempts == 1
    await run_once(settings, app.state.db, flaky, now + timedelta(minutes=1))
    await run_once(settings, app.state.db, flaky, now + timedelta(minutes=7))
    [row] = await sql(database, "SELECT status, attempts FROM email_outbox")
    assert (row["status"], row["attempts"], flaky.attempts) == ("failed", 3, 3)


async def test_an_email_that_may_have_gone_out_is_not_retried(client, app, database):
    account = await register(client, app)
    await queue_alert(app, account)
    flaky = FlakySender(EmailDeliveryError("timed out after sending", definite=False))
    await run_once(worker_settings(), app.state.db, flaky, datetime.now(UTC) + timedelta(seconds=5))
    assert await statuses(database, account["user"]["id"]) == [("security_sign_in", "unknown")]
    assert flaky.attempts == 1


# ----------------------------------------------------------------------- reminders
async def reminder_student(
    client, app, database, *, study_time: str | None = None, display_name: str | None = None, **prefs
):
    account = await register(client, app)
    headers = account["headers"]
    me = (await client.get("/v1/me", headers=headers)).json()
    profile = {"timezone": "Asia/Kolkata"}
    if display_name is not None:
        profile["displayName"] = display_name
    await client.patch("/v1/me/profile", json={"version": me["profileVersion"], "set": profile}, headers=headers)
    if study_time:
        await client.patch(
            "/v1/learning/profile", json={"version": 0, "set": {"preferredStudyTime": study_time}}, headers=headers
        )
    flags = {"dailyReminder": False, "streakWarning": False, "weeklySummary": False} | prefs
    await client.patch("/v1/notifications/preferences", json={"version": 0, "set": flags}, headers=headers)
    return account


def ist(moment: str) -> datetime:
    """A moment in India (UTC+05:30), as UTC. Dates are in 2030 so every row the API wrote is older."""
    return datetime.fromisoformat(moment + "+05:30").astimezone(UTC)


async def active_days(database: str, account, *days: date) -> None:
    for day in days:
        await sql(
            database,
            "INSERT INTO activity_days (user_id, local_date, active_seconds) VALUES (:id, :day, 600)",
            id=uuid.UUID(account["user"]["id"]),
            day=day,
        )


async def test_the_daily_reminder_comes_once_in_the_hour_from_the_study_time(client, app, database):
    account = await reminder_student(
        client, app, database, study_time="17:30", display_name="Aditi Kumar", dailyReminder=True
    )
    assert (await run(app, ist("2030-01-08T17:29")))["reminders"]["queued"] == 0
    assert (await run(app, ist("2030-01-08T17:30")))["reminders"]["queued"] == 1
    assert (await run(app, ist("2030-01-08T18:10")))["reminders"]["queued"] == 0  # one per day
    assert (await run(app, ist("2030-01-09T18:31")))["reminders"]["queued"] == 0  # the hour has passed
    mail = sent_to(app, account["email"])[-1]
    assert mail["subject"].startswith("Time for today's")
    assert "Hi Aditi," in mail["body"]
    assert f"{APP_URL}/unsubscribe?token=" in mail["body"]


async def test_no_daily_reminder_for_a_student_already_active_today(client, app, database):
    account = await reminder_student(client, app, database, dailyReminder=True)
    await active_days(database, account, date(2030, 1, 8))
    assert (await run(app, ist("2030-01-08T18:05")))["reminders"]["queued"] == 0


async def test_no_reminders_without_a_confirmed_time_zone(client, app, database):
    account = await register(client, app)
    await client.patch(
        "/v1/notifications/preferences", json={"version": 0, "set": {"dailyReminder": True}}, headers=account["headers"]
    )
    report = await run(app, ist("2030-01-08T18:05"))
    assert report["reminders"] == {"considered": 0, "queued": 0}


async def learning_days(database: str, account, *days: date) -> None:
    for day in days:
        await sql(
            database,
            "INSERT INTO learning_daily_activity (user_id, activity_date) VALUES (:id, :day)",
            id=uuid.UUID(account["user"]["id"]),
            day=day,
        )


async def test_the_streak_warning_comes_in_the_evening_before_a_streak_ends(client, app, database):
    account = await reminder_student(client, app, database, streakWarning=True)
    await learning_days(database, account, date(2030, 1, 6), date(2030, 1, 7))
    assert (await run(app, ist("2030-01-08T19:59")))["reminders"]["queued"] == 0
    assert (await run(app, ist("2030-01-08T20:00")))["reminders"]["queued"] == 1
    assert (await run(app, ist("2030-01-08T21:00")))["reminders"]["queued"] == 0
    assert sent_to(app, account["email"])[-1]["subject"] == "Keep your 2-day streak going"
    # The same reminder in the app, once (it shares its key with the one made when the bell is read).
    kinds = await sql(database, "SELECT kind, dedup_key FROM user_notifications")
    assert kinds == [{"kind": "streak_reminder", "dedup_key": "streak-reminder:2030-01-08"}]


async def test_no_streak_warning_for_a_single_day(client, app, database):
    account = await reminder_student(client, app, database, streakWarning=True)
    await learning_days(database, account, date(2030, 1, 7))
    assert (await run(app, ist("2030-01-08T20:30")))["reminders"]["queued"] == 0


async def test_the_weekly_summary_comes_on_monday_morning_about_last_week(client, app, database):
    account = await reminder_student(client, app, database, weeklySummary=True)
    await active_days(database, account, date(2030, 1, 1), date(2030, 1, 3))  # Tuesday, Thursday
    assert (await run(app, ist("2030-01-07T07:59")))["reminders"]["queued"] == 0  # Monday, too early
    assert (await run(app, ist("2030-01-07T08:00")))["reminders"]["queued"] == 1
    assert (await run(app, ist("2030-01-07T11:00")))["reminders"]["queued"] == 0
    mail = sent_to(app, account["email"])[-1]
    assert "31 Dec – 06 Jan 2030" in mail["subject"]
    assert "about 20 min" in mail["body"] and "2 of 7" in mail["body"]


async def test_reminders_follow_the_rollout(client, app, database):
    account = await reminder_student(client, app, database, dailyReminder=True)
    await run(app, ist("2030-01-08T18:05"), notifications_mode="dry_run")
    assert await statuses(database, account["user"]["id"]) == [("daily_reminder", "dry_run")]
    report = await run(app, ist("2030-01-09T18:05"), notifications_kinds="weekly_summary")
    assert report["reminders"] == {"considered": 0, "queued": 0}


# ----------------------------------------------------------------------- retention
async def test_retention_deletes_expired_sessions_and_old_counters_and_codes(client, app, database):
    account = await register(client, app)
    user_id = uuid.UUID(account["user"]["id"])
    await sql(
        database, "UPDATE auth_sessions SET expires_at = now() - interval '1 minute' WHERE user_id = :id", id=user_id
    )
    await sql(
        database,
        "INSERT INTO auth_attempts (scope, key_hash, created_at) VALUES ('login_fail', 'x', now() - interval '2 days')",
    )
    await sql(
        database,
        "INSERT INTO email_codes (email, purpose, code_hash, expires_at) "
        "VALUES (:e, 'reset_password', 'x', now() - interval '2 days')",
        e=account["email"],
    )
    report = await run(app)
    assert report["retention"]["sessions"] == 1
    assert report["retention"]["auth_attempts"] >= 1
    assert report["retention"]["email_codes"] >= 1
    assert (await sql(database, "SELECT count(*) AS n FROM auth_sessions WHERE user_id = :id", id=user_id))[0]["n"] == 0


async def test_sent_emails_lose_their_address_and_text_after_a_week(client, app, database):
    account = await register(client, app)
    await queue_alert(app, account)
    await run(app)
    await run(app, now=datetime.now(UTC) + timedelta(days=8))
    [row] = await sql(database, "SELECT kind, status, to_address, subject, body FROM email_outbox")
    assert (row["kind"], row["status"]) == ("security_sign_in", "sent")
    assert (row["to_address"], row["subject"], row["body"]) == ("", "", "")
    await run(app, now=datetime.now(UTC) + timedelta(days=89))
    assert len(await sql(database, "SELECT id FROM email_outbox")) == 1
    await run(app, now=datetime.now(UTC) + timedelta(days=91))  # 90 days after it was sent
    assert await sql(database, "SELECT id FROM email_outbox") == []


def test_the_worker_refuses_unsafe_notification_settings():
    assert worker_settings().jobs_problems() == []
    assert make_settings(notifications_mode="on").jobs_problems()  # no PUBLIC_APP_URL
    assert worker_settings(notifications_mode="allowlist").jobs_problems()  # an empty allowlist
    with pytest.raises(ValueError):
        make_settings(notifications_mode="loud")
