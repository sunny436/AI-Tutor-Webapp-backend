"""Account and session logic. All state lives in PostgreSQL.

Anti-enumeration: sign-up, resend and forgot-password always answer 202, and a
login for an unknown email costs the same argon2 time as a wrong password.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.emails import EmailSender, code_email
from app.auth.security import Passwords, hash_code, hash_key, hash_token, new_email_code, new_session_token
from app.db.models import AuthAttempt, AuthSession, EmailCode, User, UserSettings
from app.errors import (
    EmailNotVerified,
    InvalidCode,
    InvalidCredentials,
    RateLimited,
    ServiceUnavailable,
    ValidationFailed,
)
from app.logging import get_logger
from app.settings import Settings

log = get_logger("app.auth")

MAX_PREFERENCES_BYTES = 4096


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class ClientInfo:
    ip: str | None
    user_agent: str | None


@dataclass
class IssuedSession:
    user: User
    token: str
    expires_at: datetime


class AuthService:
    def __init__(self, db: AsyncSession, settings: Settings, passwords: Passwords, email: EmailSender) -> None:
        self.db = db
        self.settings = settings
        self.passwords = passwords
        self.email = email

    # ---------------------------------------------------------------- throttling
    async def _count_attempts(self, scope: str, key: str) -> int:
        since = utcnow() - timedelta(minutes=self.settings.auth_window_minutes)
        return (
            await self.db.scalar(
                select(func.count())
                .select_from(AuthAttempt)
                .where(
                    AuthAttempt.scope == scope,
                    AuthAttempt.key_hash == hash_key(key),
                    AuthAttempt.created_at > since,
                )
            )
            or 0
        )

    async def _record_attempt(self, scope: str, key: str) -> None:
        self.db.add(AuthAttempt(scope=scope, key_hash=hash_key(key)))

    async def _throttle(self, scope: str, key: str | None, limit: int, record: bool = True) -> None:
        if not key:
            return
        if await self._count_attempts(scope, key) >= limit:
            raise RateLimited()
        if record:
            await self._record_attempt(scope, key)

    async def prune_attempts(self) -> None:
        cutoff = utcnow() - timedelta(days=1)
        await self.db.execute(delete(AuthAttempt).where(AuthAttempt.created_at < cutoff))

    # ------------------------------------------------------------------ helpers
    async def _user_by_email(self, email: str) -> User | None:
        return await self.db.scalar(select(User).where(User.email == email))

    async def _issue_session(self, user: User, client: ClientInfo) -> IssuedSession:
        token = new_session_token()
        expires_at = utcnow() + timedelta(days=self.settings.session_ttl_days)
        self.db.add(
            AuthSession(
                user_id=user.id,
                token_hash=hash_token(token),
                expires_at=expires_at,
                user_agent=(client.user_agent or "")[:300] or None,
                ip=(client.ip or "")[:64] or None,
            )
        )
        return IssuedSession(user=user, token=token, expires_at=expires_at)

    async def _send_code(self, email: str, purpose: str) -> None:
        code = new_email_code()
        await self.db.execute(delete(EmailCode).where(EmailCode.email == email, EmailCode.purpose == purpose))
        self.db.add(
            EmailCode(
                email=email,
                purpose=purpose,
                code_hash=hash_code(self.settings, email, purpose, code),
                expires_at=utcnow() + timedelta(minutes=self.settings.email_code_ttl_minutes),
            )
        )
        subject, body = code_email(self.settings.app_name, purpose, code, self.settings.email_code_ttl_minutes)
        await self._deliver(email, subject, body)

    async def _deliver(self, to: str, subject: str, body: str) -> None:
        try:
            await self.email.send(to, subject, body)
        except Exception as error:  # noqa: BLE001
            log.error("email delivery failed", extra={"error_type": type(error).__name__})
            raise ServiceUnavailable("We could not send the email. Please try again shortly.") from error

    async def _consume_code(self, email: str, purpose: str, code: str) -> None:
        row = await self.db.scalar(
            select(EmailCode)
            .where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.consumed_at.is_(None))
            .order_by(EmailCode.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if row is None or row.expires_at <= utcnow() or row.attempts >= self.settings.email_code_max_attempts:
            raise InvalidCode()
        if row.code_hash != hash_code(self.settings, email, purpose, code):
            row.attempts += 1
            await self.db.commit()
            raise InvalidCode()
        row.consumed_at = utcnow()

    # ---------------------------------------------------------------- flows
    async def signup(self, email: str, password: str, display_name: str | None, client: ClientInfo) -> None:
        await self._throttle("signup_ip", client.ip, self.settings.signup_attempts_per_ip)
        await self._throttle("code_email", email, self.settings.code_requests_per_email)
        user = await self._user_by_email(email)
        if user is not None and user.email_verified_at is not None:
            # Already registered: tell the owner, reveal nothing to the caller.
            await self._deliver(
                email,
                f"Sign-up attempt on your {self.settings.app_name} account",
                "Someone tried to create an account with this email address. "
                "If it was you, sign in or reset your password instead.",
            )
            await self.db.commit()
            return
        password_hash = await self.passwords.hash(password)
        if user is None:
            user = User(email=email, password_hash=password_hash, display_name=display_name)
            self.db.add(user)
        else:  # unverified: the latest sign-up wins; only the mailbox owner can verify it
            user.password_hash = password_hash
            user.display_name = display_name or user.display_name
            user.updated_at = utcnow()
        await self.db.flush()
        await self._send_code(email, "verify_email")
        await self.db.commit()

    async def verify_email(self, email: str, code: str, client: ClientInfo) -> IssuedSession:
        await self._consume_code(email, "verify_email", code)
        user = await self._user_by_email(email)
        if user is None:
            raise InvalidCode()
        if user.email_verified_at is None:
            user.email_verified_at = utcnow()
        issued = await self._issue_session(user, client)
        await self.db.commit()
        return issued

    async def login(self, email: str, password: str, client: ClientInfo) -> IssuedSession:
        await self._throttle("login_ip", client.ip, self.settings.login_attempts_per_ip)
        await self._throttle("login_fail", email, self.settings.login_failures_per_email, record=False)
        user = await self._user_by_email(email)
        valid, needs_rehash = await self.passwords.verify(user.password_hash if user else None, password)
        if not valid or user is None:
            await self._record_attempt("login_fail", email)
            await self.db.commit()
            raise InvalidCredentials()
        if user.email_verified_at is None:
            await self.db.commit()
            raise EmailNotVerified()
        if needs_rehash:
            user.password_hash = await self.passwords.hash(password)
        issued = await self._issue_session(user, client)
        await self.db.commit()
        return issued

    async def resend_code(self, email: str, purpose: str, client: ClientInfo) -> None:
        await self._throttle("code_ip", client.ip, self.settings.signup_attempts_per_ip)
        await self._throttle("code_email", email, self.settings.code_requests_per_email)
        user = await self._user_by_email(email)
        if user is not None:
            unverified = user.email_verified_at is None
            if (purpose == "verify_email" and unverified) or (purpose == "reset_password" and not unverified):
                await self._send_code(email, purpose)
        await self.db.commit()

    async def forgot_password(self, email: str, client: ClientInfo) -> None:
        await self.resend_code(email, "reset_password", client)

    async def reset_password(self, email: str, code: str, new_password: str, client: ClientInfo) -> IssuedSession:
        await self._consume_code(email, "reset_password", code)
        user = await self._user_by_email(email)
        if user is None:
            raise InvalidCode()
        user.password_hash = await self.passwords.hash(new_password)
        user.email_verified_at = user.email_verified_at or utcnow()
        user.updated_at = utcnow()
        await self.db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        issued = await self._issue_session(user, client)
        await self.db.commit()
        return issued

    async def change_password(self, user: User, session_id: uuid.UUID, current: str, new: str) -> None:
        valid, _ = await self.passwords.verify(user.password_hash, current)
        if not valid:
            raise InvalidCredentials("The current password is incorrect.")
        user.password_hash = await self.passwords.hash(new)
        user.updated_at = utcnow()
        await self.revoke_other_sessions(user.id, session_id, commit=False)
        await self.db.commit()

    async def logout(self, session_id: uuid.UUID) -> None:
        await self.db.execute(delete(AuthSession).where(AuthSession.id == session_id))
        await self.db.commit()

    async def revoke_other_sessions(self, user_id: uuid.UUID, session_id: uuid.UUID, commit: bool = True) -> None:
        await self.db.execute(delete(AuthSession).where(AuthSession.user_id == user_id, AuthSession.id != session_id))
        if commit:
            await self.db.commit()

    async def update_profile(self, user: User, display_name: str | None) -> User:
        user.display_name = (display_name or "").strip() or None
        user.updated_at = utcnow()
        await self.db.commit()
        return user

    async def delete_account(self, user: User, password: str) -> None:
        valid, _ = await self.passwords.verify(user.password_hash, password)
        if not valid:
            raise InvalidCredentials("The password is incorrect.")
        await self.db.execute(delete(User).where(User.id == user.id))  # cascades to all user data
        # Codes are keyed by address, not by user, so the cascade misses them. A reset code left
        # behind would still work on a new account registered with the same address.
        await self.db.execute(delete(EmailCode).where(EmailCode.email == user.email))
        await self.db.commit()

    async def get_settings(self, user_id: uuid.UUID) -> UserSettings | None:
        return await self.db.get(UserSettings, user_id)

    async def update_settings(self, user_id: uuid.UUID, changes: dict) -> UserSettings:
        row = await self.db.get(UserSettings, user_id, with_for_update=True)
        current = dict(row.preferences) if row else {}
        for key, value in changes.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        if len(json.dumps(current)) > MAX_PREFERENCES_BYTES:
            raise ValidationFailed("Settings are too large.")
        if row is None:
            row = UserSettings(user_id=user_id, preferences=current)
            self.db.add(row)
        else:
            await self.db.execute(
                update(UserSettings)
                .where(UserSettings.user_id == user_id)
                .values(preferences=current, updated_at=func.clock_timestamp())
            )
        await self.db.commit()
        await self.db.refresh(row)
        return row
