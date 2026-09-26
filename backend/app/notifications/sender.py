"""Sends the email outbox: at most once, within each row's `send_before`, as the rollout allows.

Each run of the worker (one at a time: app/jobs/runner.py holds a PostgreSQL advisory lock):

1. **recover**: a row still `sending` from an earlier run means that run died between claiming
   and recording. The provider may or may not have delivered it, so it becomes `unknown` and
   is never sent again: a missed email is better than a duplicate.
2. **expire**: `pending` rows past `send_before` become `expired` (a sign-in alert a day late,
   yesterday's reminder).
3. **send** up to NOTIFICATIONS_MAX_PER_RUN due rows, decided by NOTIFICATIONS_MODE:
   `off` sends only operational email (support forwards); `dry_run` marks student email
   `dry_run`; `allowlist` sends only to NOTIFICATIONS_ALLOWLIST and marks the rest
   `suppressed`; `on` sends. A kind missing from NOTIFICATIONS_KINDS is `suppressed`.
   A claim is committed before the provider is called. A definite refusal goes back to
   `pending` with backoff (1, 5, 15 minutes) and becomes `failed` after 3 attempts; a
   possibly delivered message (a timeout after sending) becomes `unknown`.
4. **redact**: a week after its final state an email keeps its kind and status but loses its
   address, subject and body; 90 days after it, the row is deleted. Both count from the final
   state, so a row is never deleted while it can still be sent, and a reminder's dedup key
   outlives its period.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update

from app.auth.emails import EmailDeliveryError, EmailSender
from app.db.models import EmailOutbox
from app.db.session import Database
from app.logging import get_logger
from app.notifications.outbox import OPERATIONAL_KINDS
from app.settings import Settings

log = get_logger("app.notifications")

MAX_ATTEMPTS = 3
BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15))
STUCK_AFTER = timedelta(minutes=5)
REDACT_AFTER = timedelta(days=7)
DELETE_AFTER = timedelta(days=90)


@dataclass
class SendReport:
    sent: int = 0
    retried: int = 0
    failed: int = 0
    unknown: int = 0
    dry_run: int = 0
    suppressed: int = 0


def decide(row: EmailOutbox, settings: Settings) -> str:
    """What this run does with a due row: send it, or mark it `dry_run` or `suppressed`."""
    if row.kind in OPERATIONAL_KINDS:
        return "send"
    kinds = settings.notification_kinds
    if kinds is not None and row.kind not in kinds:
        return "suppressed"
    if settings.notifications_mode == "dry_run":
        return "dry_run"
    if settings.notifications_mode == "allowlist":
        allowed = settings.notification_allowlist
        if not {str(row.user_id), row.to_address.lower()} & allowed:
            return "suppressed"
    return "send"


async def recover_stuck(db: Database, now: datetime) -> int:
    async with db.sessionmaker() as session:
        result = await session.execute(
            update(EmailOutbox)
            .where(EmailOutbox.status == "sending", EmailOutbox.claimed_at < now - STUCK_AFTER)
            .values(status="unknown", final_at=now)
        )
        await session.commit()
    if result.rowcount:
        log.warning("outbox rows left sending by an earlier run marked unknown", extra={"count": result.rowcount})
    return result.rowcount


async def expire_stale(db: Database, now: datetime) -> int:
    async with db.sessionmaker() as session:
        result = await session.execute(
            update(EmailOutbox)
            .where(EmailOutbox.status == "pending", EmailOutbox.send_before < now)
            .values(status="expired", final_at=now)
        )
        await session.commit()
    return result.rowcount


def _definite(error: BaseException) -> bool:
    """False when the provider may have delivered the message despite the error."""
    if isinstance(error, EmailDeliveryError):
        return error.definite
    return not isinstance(error, (TimeoutError, socket.timeout))


async def send_due(
    db: Database, settings: Settings, email: EmailSender, now: datetime, *, student_email: bool = True
) -> SendReport:
    """Send what is due. With `student_email` False (mode off, or a configuration problem),
    only operational email is considered."""
    report = SendReport()
    async with db.sessionmaker() as session:
        query = (
            select(EmailOutbox)
            .where(
                EmailOutbox.status == "pending",
                EmailOutbox.next_attempt_at <= now,
                EmailOutbox.send_before >= now,
            )
            .order_by(EmailOutbox.created_at)
            .limit(settings.notifications_max_per_run)
            .with_for_update(skip_locked=True)
        )
        if not student_email or settings.notifications_mode == "off":
            query = query.where(EmailOutbox.kind.in_(OPERATIONAL_KINDS))
        claimed = []
        for row in (await session.scalars(query)).all():
            decision = decide(row, settings)
            if decision == "send":
                row.status, row.claimed_at, row.attempts = "sending", now, row.attempts + 1
                claimed.append((row.id, row.to_address, row.subject, row.body, row.attempts))
            else:
                row.status, row.final_at = decision, now
                setattr(report, decision, getattr(report, decision) + 1)
        await session.commit()  # claims are durable before anything is sent

    for row_id, to, subject, body, attempts in claimed:
        try:
            await email.send(to, subject, body)
        except Exception as error:  # noqa: BLE001 - every outcome is recorded, none raised
            if not _definite(error):
                values = {"status": "unknown", "final_at": now}
                report.unknown += 1
            elif attempts >= MAX_ATTEMPTS:
                values = {"status": "failed", "final_at": now}
                report.failed += 1
            else:
                values = {"status": "pending", "next_attempt_at": now + BACKOFF[attempts - 1]}
                report.retried += 1
            log.warning(
                "outbox send failed",
                extra={"error_type": type(error).__name__, "attempts": attempts, "outcome": values["status"]},
            )
        else:
            values = {"status": "sent", "final_at": now}
            report.sent += 1
        async with db.sessionmaker() as session:
            await session.execute(update(EmailOutbox).where(EmailOutbox.id == row_id).values(**values))
            await session.commit()
    return report


async def redact_old(db: Database, now: datetime) -> dict[str, int]:
    async with db.sessionmaker() as session:
        redacted = await session.execute(
            update(EmailOutbox)
            .where(EmailOutbox.final_at < now - REDACT_AFTER, EmailOutbox.to_address != "")
            .values(to_address="", subject="", body="")
        )
        deleted = await session.execute(delete(EmailOutbox).where(EmailOutbox.final_at < now - DELETE_AFTER))
        await session.commit()
    return {"outbox_redacted": redacted.rowcount, "outbox_deleted": deleted.rowcount}
