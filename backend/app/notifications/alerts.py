"""Security emails, queued by the auth flows in their own transaction (app/auth/service.py).

- A sign-in from a device the account has no live session on: an alert, unless the student
  turned sign-in alerts off.
- A password change or reset: always, since it is the one email that tells the owner someone
  else may have taken the account.

Both go through the outbox, so they follow NOTIFICATIONS_MODE like every student email, and
both may be sent up to a day late (after that they expire, unsent). Both also appear in the
app's bell at once (app/notifications/inbox.py), whatever the email switches say.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationPreferences, User
from app.notifications import emails
from app.notifications.inbox import notify
from app.notifications.outbox import SECURITY_PASSWORD_CHANGED, SECURITY_SIGN_IN, queue_email
from app.notifications.tokens import unsubscribe_url
from app.progress.activity import zone_for
from app.settings import Settings

ALERT_LIFETIME = timedelta(days=1)


def settings_link(settings: Settings, section: str = "notifications") -> str:
    base = settings.public_app_url.rstrip("/")
    return f"{base}/settings/{section}" if base else f"{settings.app_name} Settings"


def local_time(settings: Settings, user: User, moment: datetime) -> str:
    zone = zone_for(user.timezone, settings.default_timezone)
    return f"{moment.astimezone(zone):%d %b %Y, %H:%M} ({zone.key})"


async def queue_sign_in_alert(
    session: AsyncSession, settings: Settings, user: User, device: str, moment: datetime
) -> bool:
    # In the app always; by email unless the student turned sign-in alerts off.
    await notify(
        session,
        user.id,
        kind="security_sign_in",
        title="New sign-in to your account",
        body=f"{device}, {local_time(settings, user, moment)}. Not you? Change your password now.",
        link="/settings/privacy",
        dedup_key=f"security-sign-in:{uuid.uuid4()}",
    )
    preferences = await session.get(NotificationPreferences, user.id)
    if preferences is not None and not preferences.security_alerts:
        return False
    unsubscribe = unsubscribe_url(settings, user.id, SECURITY_SIGN_IN) if settings.public_app_url else None
    subject, body = emails.sign_in_alert(
        settings.app_name, device, local_time(settings, user, moment), settings_link(settings), unsubscribe
    )
    return await queue_email(
        session,
        kind=SECURITY_SIGN_IN,
        to=user.email,
        subject=subject,
        body=body,
        send_before=moment + ALERT_LIFETIME,
        user_id=user.id,
    )


async def queue_password_changed(session: AsyncSession, settings: Settings, user: User, moment: datetime) -> bool:
    await notify(
        session,
        user.id,
        kind="security_password_changed",
        title="Your password was changed",
        body=f"{local_time(settings, user, moment)}. Not you? Reset your password now.",
        link="/settings/privacy",
        dedup_key=f"security-password:{uuid.uuid4()}",
    )
    subject, body = emails.password_changed(
        settings.app_name, local_time(settings, user, moment), settings_link(settings, "privacy")
    )
    return await queue_email(
        session,
        kind=SECURITY_PASSWORD_CHANGED,
        to=user.email,
        subject=subject,
        body=body,
        send_before=moment + ALERT_LIFETIME,
        user_id=user.id,
    )
