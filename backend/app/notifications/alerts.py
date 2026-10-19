"""Security notices, raised by the internal auth events (app/auth/internal.py) after the web app's
Better Auth signed someone in or changed how they sign in.

- A sign-in from a device the account has no other live session on: an alert, emailed unless
  the student turned sign-in alerts off.
- A password change or reset, a Google account linked, and two-step sign-in turned on or off:
  always emailed, since each is how the owner learns that someone else may have taken the account.

Each notice is written to the app's bell at once (app/notifications/inbox.py) and returned as an
email for the caller to send right after it commits. They are transactional, like sign-in codes:
they do not wait for the outbox or follow NOTIFICATIONS_MODE (owner's decision, 2026-10-01).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationPreferences, User
from app.email_html import Email, app_link
from app.notifications import emails
from app.notifications.inbox import notify
from app.notifications.outbox import SECURITY_SIGN_IN
from app.notifications.tokens import unsubscribe_url
from app.progress.activity import zone_for
from app.settings import Settings


def settings_link(settings: Settings, section: str = "notifications") -> str:
    return app_link(settings, section) or f"{settings.app_name} Settings"


def local_time(settings: Settings, user: User, moment: datetime) -> str:
    zone = zone_for(user.timezone, settings.default_timezone)
    return f"{moment.astimezone(zone):%d %b %Y, %H:%M} ({zone.key})"


async def sign_in_alert(
    session: AsyncSession, settings: Settings, user: User, device: str, moment: datetime
) -> Email | None:
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
        return None
    unsubscribe = unsubscribe_url(settings, user.id, SECURITY_SIGN_IN) if settings.public_app_url else None
    return emails.sign_in_alert(
        settings.app_name,
        device,
        local_time(settings, user, moment),
        settings_link(settings),
        unsubscribe,
        settings=settings,
    )


async def password_changed_alert(
    session: AsyncSession, settings: Settings, user: User, moment: datetime, *, reset: bool = False
) -> Email:
    await notify(
        session,
        user.id,
        kind="security_password_changed",
        title="Your password was changed",
        body=f"{local_time(settings, user, moment)}. Not you? Reset your password now.",
        link="/settings/privacy",
        dedup_key=f"security-password:{uuid.uuid4()}",
    )
    return emails.password_changed(
        settings.app_name,
        local_time(settings, user, moment),
        settings_link(settings, "privacy"),
        reset=reset,
        settings=settings,
    )


async def google_linked_alert(session: AsyncSession, settings: Settings, user: User, moment: datetime) -> Email:
    await notify(
        session,
        user.id,
        kind="security_google_linked",
        title="Google sign-in was added",
        body=f"{local_time(settings, user, moment)}. Not you? Disconnect it in Settings and change your password.",
        link="/settings/privacy",
        dedup_key=f"security-google:{uuid.uuid4()}",
    )
    return emails.google_linked(
        settings.app_name, local_time(settings, user, moment), settings_link(settings, "privacy"), settings=settings
    )


async def two_factor_alert(session: AsyncSession, settings: Settings, user: User, on: bool, moment: datetime) -> Email:
    await notify(
        session,
        user.id,
        kind="security_two_factor_on" if on else "security_two_factor_off",
        title="Two-step sign-in was turned on" if on else "Two-step sign-in was turned off",
        body=f"{local_time(settings, user, moment)}. Not you? Change your password now.",
        link="/settings/privacy",
        dedup_key=f"security-two-factor:{uuid.uuid4()}",
    )
    return emails.two_factor(
        settings.app_name, on, local_time(settings, user, moment), settings_link(settings, "privacy"), settings=settings
    )
