"""Unsubscribe links that work without signing in, and cannot be forged or aimed elsewhere.

A token names one user and one kind of email, and is signed with SECRET_KEY under its own
purpose prefix (so no other HMAC in the app can be replayed as one). It does not expire: an
old email's link must keep working. Using it twice is harmless (the preference is already off).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from app.email_html import app_link
from app.settings import Settings

PURPOSE = "padhai-unsubscribe-v1"

# Which preference each kind of email is switched off by.
PREFERENCE_OF = {
    "daily_reminder": "daily_reminder",
    "streak_warning": "streak_warning",
    "weekly_summary": "weekly_summary",
    "security_sign_in": "security_alerts",
}


def _signature(settings: Settings, payload: str) -> str:
    key = settings.secret_key.get_secret_value().encode()
    return hmac.new(key, f"{PURPOSE}|{payload}".encode(), hashlib.sha256).hexdigest()[:32]


def make_token(settings: Settings, user_id: uuid.UUID, kind: str) -> str:
    if kind not in PREFERENCE_OF:
        raise ValueError(f"{kind!r} emails have no unsubscribe link")
    payload = f"{user_id}:{kind}"
    encoded = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{encoded}.{_signature(settings, payload)}"


def read_token(settings: Settings, token: str) -> tuple[uuid.UUID, str] | None:
    """(user id, kind), or None for anything that is not a token this server signed."""
    encoded, _, signature = token.partition(".")
    try:
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        user_text, kind = payload.split(":")
        user_id = uuid.UUID(user_text)
    except ValueError:
        return None
    if kind not in PREFERENCE_OF or not hmac.compare_digest(signature, _signature(settings, payload)):
        return None
    return user_id, kind


def unsubscribe_url(settings: Settings, user_id: uuid.UUID, kind: str) -> str:
    base = app_link(settings, "home")
    if base is None:
        raise ValueError("PUBLIC_APP_URL is not a valid application origin")
    return f"{base.rstrip('/')}/unsubscribe?token={make_token(settings, user_id, kind)}"
