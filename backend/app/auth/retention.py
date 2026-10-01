"""What auth keeps, and for how long. Run every hour by the API itself (app/main.py), so it never
depends on the jobs worker; the worker (python -m app.jobs) runs it too when enabled.

- A session is deleted once it has expired, and with it the IP address and user agent it
  kept. (Signing out or revoking a device deletes its session at once.)
- Throttling counters (auth_attempts, hashed keys only) matter for at most a day (the longest
  window); they are deleted after a day.
- Email codes (email_codes, and Better Auth's auth_verifications: codes and OAuth states) are
  deleted a day after they expire.
- An account that never proved its address (Better Auth only creates these for a Google
  address Google itself has not verified) and has no session is deleted after a week. It never
  signed in, so it holds no data.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthAttempt, AuthSession, AuthVerification, EmailCode, User

ATTEMPTS_KEPT = timedelta(days=1)
CODES_KEPT_AFTER_EXPIRY = timedelta(days=1)
UNVERIFIED_KEPT = timedelta(days=7)


async def purge_expired(session: AsyncSession, now: datetime) -> dict[str, int]:
    sessions = await session.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    attempts = await session.execute(delete(AuthAttempt).where(AuthAttempt.created_at < now - ATTEMPTS_KEPT))
    codes = await session.execute(delete(EmailCode).where(EmailCode.expires_at < now - CODES_KEPT_AFTER_EXPIRY))
    verifications = await session.execute(
        delete(AuthVerification).where(AuthVerification.expires_at < now - CODES_KEPT_AFTER_EXPIRY)
    )
    unverified = await session.execute(
        delete(User).where(
            User.email_verified.is_(False),
            User.created_at < now - UNVERIFIED_KEPT,
            ~exists(select(AuthSession.id).where(AuthSession.user_id == User.id)),
        )
    )
    return {
        "sessions": sessions.rowcount,
        "auth_attempts": attempts.rowcount,
        "email_codes": codes.rowcount,
        "auth_verifications": verifications.rowcount,
        "unverified_users": unverified.rowcount,
    }
