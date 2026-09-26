"""One run of the jobs worker. `python -m app.jobs` runs it once and exits; the systemd timer
aichat-jobs.timer starts it every minute (deploy/systemd/aichat-jobs.*).

Why a separate one-shot process, not a scheduler inside the API: the API also runs as a
deploy's trial copy (which must never send email), it would compete with requests, and it would
lose its schedule on every restart. The worker is stateless: every run works out what is due
from the database, so a missed run is simply caught up by the next one.

- **One at a time:** the run holds a PostgreSQL advisory lock; a second worker (another host,
  a manual run) finds it taken and exits at once. systemd also never starts the unit while it
  is still running.
- **Rollout:** JOBS_ENABLED=false makes a run exit immediately. NOTIFICATIONS_MODE and the
  other settings are read from api.env on every run (docs/deployment.md, "Jobs worker").
- **Each step is independent:** one that fails is logged and the others still run.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import text

from app.auth.emails import EmailSender
from app.auth.retention import purge_expired
from app.db.session import Database
from app.logging import get_logger
from app.notifications.inbox import purge_read
from app.notifications.reminders import plan_reminders
from app.notifications.sender import expire_stale, recover_stuck, redact_old, send_due
from app.settings import Settings

log = get_logger("app.jobs")

LOCK_KEY = 7_216_094_001  # pg advisory lock id of the jobs worker (any constant unique to this app)


async def run_once(settings: Settings, db: Database, email: EmailSender, now: datetime | None = None) -> dict:
    if not settings.jobs_enabled:
        return {"skipped": "JOBS_ENABLED is false"}
    now = now or datetime.now(UTC)
    report: dict = {}
    async with db.engine.connect() as lock:
        if not await lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}):
            return {"skipped": "another run holds the lock"}
        try:
            problems = settings.jobs_problems()
            for problem in problems:
                log.error("jobs configuration problem: student emails are off this run", extra={"problem": problem})
            student_email = settings.notifications_mode != "off" and not problems

            async def step(name: str, work: Callable[[], Awaitable[object]]) -> None:
                try:
                    report[name] = await work()
                except Exception as error:  # noqa: BLE001 - a failed step must not stop the others
                    log.exception("jobs step failed", extra={"step": name, "error_type": type(error).__name__})
                    report[name] = "failed"

            async def retention() -> dict:
                async with db.sessionmaker() as session:
                    purged = await purge_expired(session, now)
                    purged["notifications"] = await purge_read(session, now)
                    await session.commit()
                return purged | await redact_old(db, now)

            async def reminders() -> object:
                if not student_email:
                    return "off"
                async with db.sessionmaker() as session:
                    planned = await plan_reminders(session, settings, now)
                    await session.commit()
                return {"considered": planned.considered, "queued": planned.queued}

            await step("recovered", lambda: recover_stuck(db, now))
            await step("expired", lambda: expire_stale(db, now))
            await step("reminders", reminders)
            await step("send", lambda: _as_dict(send_due(db, settings, email, now, student_email=student_email)))
            await step("retention", retention)
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
            await lock.commit()
    return report


async def _as_dict(report_awaitable) -> dict:
    report = await report_awaitable
    return {key: value for key, value in vars(report).items() if value}
