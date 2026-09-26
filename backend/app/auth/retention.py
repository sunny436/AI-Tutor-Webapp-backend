"""What auth keeps, and for how long. Run by the jobs worker (python -m app.jobs).

- A session is deleted once it has expired, and with it the IP address and user agent it
  kept. (Signing out or revoking a device deletes its session at once.)
- Throttling counters (auth_attempts, hashed keys only) matter for AUTH_WINDOW_MINUTES; they
  are deleted after a day.
- Email codes are deleted a day after they expire.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthAttempt, AuthSession, EmailCode

ATTEMPTS_KEPT = timedelta(days=1)
CODES_KEPT_AFTER_EXPIRY = timedelta(days=1)


async def purge_expired(session: AsyncSession, now: datetime) -> dict[str, int]:
    sessions = await session.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    attempts = await session.execute(delete(AuthAttempt).where(AuthAttempt.created_at < now - ATTEMPTS_KEPT))
    codes = await session.execute(delete(EmailCode).where(EmailCode.expires_at < now - CODES_KEPT_AFTER_EXPIRY))
    return {"sessions": sessions.rowcount, "auth_attempts": attempts.rowcount, "email_codes": codes.rowcount}
