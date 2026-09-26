"""The email outbox: how the API asks for an email to be sent to a student or to support.

A row is written in the same transaction as the event it reports (a sign-in, a password
change, a support request), so the email exists exactly when the event does. The worker
(python -m app.jobs, app/notifications/sender.py) sends it later, at most once, and only
while `send_before` has not passed: news that is too old is marked `expired` instead.

Codes the user is waiting for (sign-up, reset, email change) are NOT sent this way; they go
out directly, inside the request, because the user needs them now.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmailOutbox

SECURITY_SIGN_IN = "security_sign_in"
SECURITY_PASSWORD_CHANGED = "security_password_changed"  # noqa: S105 - an email kind, not a secret
DAILY_REMINDER = "daily_reminder"
STREAK_WARNING = "streak_warning"
WEEKLY_SUMMARY = "weekly_summary"
SUPPORT_FORWARD = "support_forward"

# Emails to students follow NOTIFICATIONS_MODE; emails to the team (support) do not.
STUDENT_KINDS = (SECURITY_SIGN_IN, SECURITY_PASSWORD_CHANGED, DAILY_REMINDER, STREAK_WARNING, WEEKLY_SUMMARY)
OPERATIONAL_KINDS = (SUPPORT_FORWARD,)
KINDS = STUDENT_KINDS + OPERATIONAL_KINDS


async def queue_email(
    session: AsyncSession,
    *,
    kind: str,
    to: str,
    subject: str,
    body: str,
    send_before: datetime,
    user_id: uuid.UUID | None = None,
    dedup_key: str | None = None,
) -> bool:
    """Add an email to the caller's transaction. With a `dedup_key`, a second email with the
    same key is not added (False is returned)."""
    if kind not in KINDS:
        raise ValueError(f"unknown email kind {kind!r}")
    statement = insert(EmailOutbox).values(
        kind=kind,
        to_address=to,
        subject=subject[:300],
        body=body,
        send_before=send_before,
        user_id=user_id,
        dedup_key=dedup_key,
    )
    if dedup_key is not None:
        statement = statement.on_conflict_do_nothing(index_elements=[EmailOutbox.dedup_key])
    return (await session.execute(statement.returning(EmailOutbox.id))).first() is not None
