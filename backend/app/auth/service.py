"""Account and session logic. All state lives in PostgreSQL.

Signing in, signing up, email codes, password reset and password change happen in the web
app's Better Auth (frontend/apps/app/src/lib/auth), on the same tables. This service keeps what
the API owns: the sessions list and revocation, the profile, photo and settings, the email
change and the account deletion, both behind re-authentication.

Throttling counts attempts in auth_attempts under a per-key advisory lock, so a burst of
parallel requests can never pass more attempts than the limit (Better Auth's hooks use the same
scopes, keys and lock).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.avatar import ProcessedAvatar
from app.auth.emails import EmailSender, account_deleted_email, code_email, email_changed_email, email_in_use_email
from app.auth.security import Passwords, hash_code, hash_key, new_email_code
from app.db.models import (
    AuthAccount,
    AuthAttempt,
    AuthSession,
    AuthVerification,
    EmailCode,
    User,
    UserAvatar,
    UserSettings,
)
from app.email_html import Email
from app.errors import (
    Conflict,
    InvalidCode,
    InvalidCredentials,
    NotFound,
    RateLimited,
    ServiceUnavailable,
    ValidationFailed,
    VersionConflict,
)
from app.logging import get_logger
from app.settings import Settings

log = get_logger("app.auth")

MAX_PREFERENCES_BYTES = 4096
# File Library uploads per student (app/files): per AUTH_WINDOW_MINUTES, and per day.
FILES_UPLOADS_PER_WINDOW = 20
FILES_UPLOADS_PER_DAY = 30
# Password checks per account, wherever they happen (Better Auth's sign-in and change-password,
# and the re-authentication here): the same scope, key and window in both runtimes.
SIGNIN_SCOPE = "signin_email"
SIGNIN_LIMIT = 10
SIGNIN_WINDOW_MINUTES = 15
# An account without a password re-authenticates by having signed in this recently.
REAUTH_FRESH = timedelta(minutes=15)
# Better Auth's email-code types, as its verification identifiers name them ("<type>-otp-<email>").
OTP_TYPES = ("sign-in", "forget-password", "email-verification", "change-email")


def otp_identifiers(email: str) -> list[str]:
    return [f"{kind}-otp-{email.lower()}" for kind in OTP_TYPES]


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class ClientInfo:
    ip: str | None
    user_agent: str | None


class AuthService:
    def __init__(self, db: AsyncSession, settings: Settings, passwords: Passwords, email: EmailSender) -> None:
        self.db = db
        self.settings = settings
        self.passwords = passwords
        self.email = email

    # ---------------------------------------------------------------- throttling
    async def _count_attempts(self, scope: str, key: str, minutes: int | None = None) -> int:
        since = utcnow() - timedelta(minutes=minutes or self.settings.auth_window_minutes)
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

    async def _throttle(self, scope: str, key: str | None, limit: int, minutes: int | None = None) -> None:
        """Count this attempt, or refuse it when `limit` were made in the window. The advisory lock
        (held until the caller commits) makes count-and-insert atomic per scope and key: parallel
        attempts queue on it instead of all reading the same count. A refused attempt is not
        recorded, so the limit lifts once the window passes."""
        if not key:
            return
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"{scope}|{hash_key(key)}"}
        )
        if await self._count_attempts(scope, key, minutes) >= limit:
            raise RateLimited()
        self.db.add(AuthAttempt(scope=scope, key_hash=hash_key(key)))
        await self.db.flush()

    # ------------------------------------------------------------------ helpers
    async def _user_by_email(self, email: str) -> User | None:
        return await self.db.scalar(select(User).where(User.email == email))

    async def _deliver(self, to: str, email: Email) -> None:
        try:
            await self.email.send(to, email.subject, email.body, html=email.html)
        except Exception as error:  # noqa: BLE001
            log.error("email delivery failed", extra={"error_type": type(error).__name__})
            raise ServiceUnavailable("We could not send the email. Please try again shortly.") from error

    async def reauthenticate(self, user: User, session: AuthSession, password: str | None) -> None:
        """Confirm it is the owner before a sensitive change: the account's password, throttled
        per account, or, for an account without one (Google only), a sign-in within REAUTH_FRESH.
        The attempt is committed before argon2 runs, so no pooled connection waits on the hash.
        An account with two-step sign-in also needs a full sign-in (both steps) within
        REAUTH_FRESH: a stolen session plus the password is not enough."""
        if user.two_factor_enabled and session.created_at <= utcnow() - REAUTH_FRESH:
            await self.db.commit()
            raise Conflict("Sign in again to confirm it's you.", code="reauth_required")
        stored = await self.db.scalar(
            select(AuthAccount.password).where(AuthAccount.user_id == user.id, AuthAccount.provider_id == "credential")
        )
        if not stored:
            await self.db.commit()
            if session.created_at <= utcnow() - REAUTH_FRESH:
                raise Conflict("Sign in again to confirm it's you.", code="reauth_required")
            return
        if not password:
            await self.db.commit()
            raise ValidationFailed("Enter your password.", fields=[{"field": "password", "reason": "missing"}])
        await self._throttle(SIGNIN_SCOPE, user.email, SIGNIN_LIMIT, SIGNIN_WINDOW_MINUTES)
        await self.db.commit()
        valid, _ = await self.passwords.verify(stored, password)
        if not valid:
            raise InvalidCredentials("The password is incorrect.")

    # -------------------------------------------------------------------- sessions
    async def logout(self, session_id: uuid.UUID) -> None:
        await self.db.execute(delete(AuthSession).where(AuthSession.id == session_id))
        await self.db.commit()

    async def revoke_other_sessions(self, user_id: uuid.UUID, session_id: uuid.UUID, commit: bool = True) -> None:
        await self.db.execute(delete(AuthSession).where(AuthSession.user_id == user_id, AuthSession.id != session_id))
        if commit:
            await self.db.commit()

    async def update_profile(self, user: User, display_name: str | None) -> User:
        """The original PATCH /v1/me, kept for existing clients. It moves the version on too, so
        a versioned edit that raced it is refused instead of silently overwriting it."""
        user.display_name = (display_name or "").strip() or None
        user.updated_at = utcnow()
        user.profile_version = User.profile_version + 1
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # ------------------------------------------------------------ identity profile
    PROFILE_COLUMNS = {"displayName": "display_name", "timezone": "timezone"}

    async def update_profile_versioned(
        self, user: User, version: int, changes: dict[str, object], reset: list[str]
    ) -> User:
        """Compare-and-set on profile_version in one UPDATE: of two writers that read the same
        version, exactly one wins; the other gets 409 version_conflict. An empty change writes
        nothing and keeps the version."""
        values: dict[str, object] = {self.PROFILE_COLUMNS[name]: value for name, value in changes.items()}
        values.update({self.PROFILE_COLUMNS[name]: None for name in reset})
        if not values:
            return user
        result = await self.db.execute(
            update(User)
            .where(User.id == user.id, User.profile_version == version)
            .values(**values, profile_version=User.profile_version + 1, updated_at=func.clock_timestamp())
            .returning(User.id)
            .execution_options(synchronize_session=False)
        )
        won = result.first() is not None
        await self.db.commit()
        await self.db.refresh(user)
        if not won:
            raise VersionConflict()
        return user

    # --------------------------------------------------------------- profile photo
    async def throttle_avatar(self, user: User) -> None:
        """Counted before the image is decoded, so refused and failed uploads cost an attempt too."""
        await self._throttle("avatar_user", str(user.id), self.settings.avatar_uploads_per_user)
        await self.db.commit()

    async def throttle_files(self, user: User) -> None:
        """File Library uploads: FILES_UPLOADS_PER_WINDOW per auth window and FILES_UPLOADS_PER_DAY
        a day. Counted before the body is read, so refused uploads cost an attempt too (every upload
        costs embedding calls)."""
        key = str(user.id)
        if await self._count_attempts("file_upload_user", key, minutes=24 * 60) >= FILES_UPLOADS_PER_DAY:
            raise RateLimited("You've reached today's upload limit. Please try again tomorrow.")
        await self._throttle("file_upload_user", key, FILES_UPLOADS_PER_WINDOW)
        await self.db.commit()

    async def throttle_voice(self, user: User, lane: str) -> None:
        """Voice mode (app/voice), `lane` "stt" or "tts": VOICE_*_PER_MINUTE and VOICE_*_PER_DAY per student.
        Counted before OllaLink is asked, so refused and failed requests cost an attempt too."""
        settings = self.settings
        per_minute, per_day = (
            (settings.voice_transcriptions_per_minute, settings.voice_transcriptions_per_day)
            if lane == "stt"
            else (settings.voice_speech_per_minute, settings.voice_speech_per_day)
        )
        scope, key = f"voice_{lane}_user", str(user.id)
        if await self._count_attempts(scope, key, minutes=24 * 60) >= per_day:
            raise RateLimited("You've reached today's voice limit. Please try again tomorrow.")
        await self._throttle(scope, key, per_minute, minutes=1)
        await self.db.commit()

    async def set_avatar(self, user: User, avatar: ProcessedAvatar) -> User:
        # The upsert locks the photo row until commit, so concurrent uploads apply one after the
        # other and users.avatar_hash always names the stored image.
        statement = insert(UserAvatar).values(
            user_id=user.id, image=avatar.image, content_type=avatar.content_type, hash=avatar.hash
        )
        await self.db.execute(
            statement.on_conflict_do_update(
                index_elements=[UserAvatar.user_id],
                set_={
                    "image": statement.excluded.image,
                    "content_type": statement.excluded.content_type,
                    "hash": statement.excluded.hash,
                    "updated_at": func.clock_timestamp(),
                },
            )
        )
        user.avatar_hash = avatar.hash
        await self.db.commit()
        return user

    async def remove_avatar(self, user: User) -> User:
        await self.db.execute(delete(UserAvatar).where(UserAvatar.user_id == user.id))
        user.avatar_hash = None
        await self.db.commit()
        return user

    async def get_avatar(self, user_id: uuid.UUID) -> UserAvatar | None:
        return await self.db.get(UserAvatar, user_id)

    # -------------------------------------------------------------------- sessions
    async def list_sessions(self, user_id: uuid.UUID) -> list[AuthSession]:
        rows = await self.db.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.expires_at > func.now())
            .order_by(AuthSession.last_seen_at.desc(), AuthSession.id)
        )
        return list(rows)

    async def revoke_session(self, user_id: uuid.UUID, session_id: uuid.UUID, current_session_id: uuid.UUID) -> None:
        if session_id == current_session_id:
            raise Conflict("This is the device you are using. Sign out instead.", code="current_session")
        # The owner is part of the condition: another account's session is simply "not found".
        result = await self.db.execute(
            delete(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == user_id)
        )
        if result.rowcount == 0:
            raise NotFound("Session not found.")
        await self.db.commit()

    # ---------------------------------------------------------------- email change
    @staticmethod
    def _change_purpose(user_id: uuid.UUID) -> str:
        # The HMAC names the user: a change code can only ever move the account that asked for it.
        return f"change_email:{user_id}"

    async def request_email_change(
        self, user: User, session: AuthSession, new_email: str, password: str | None
    ) -> None:
        """Answers 202 whatever the address. If it is free, a code goes to it; if another account
        has it, a notice goes to it instead. Either way exactly one email is sent, so the caller
        cannot tell which happened. The email goes out after the commit, so no pooled connection
        waits on the mail provider."""
        if new_email.lower() == user.email.lower():
            raise ValidationFailed(
                "That is already your email address.", fields=[{"field": "newEmail", "reason": "unchanged"}]
            )
        await self.reauthenticate(user, session, password)
        await self._throttle("email_change_user", str(user.id), self.settings.email_change_requests_per_user)
        await self._throttle("code_email", new_email, self.settings.code_requests_per_email)
        # Only the latest request can be confirmed.
        await self.db.execute(
            delete(EmailCode).where(EmailCode.purpose == "change_email", EmailCode.user_id == user.id)
        )
        if await self._user_by_email(new_email) is not None:
            await self.db.commit()
            await self._deliver(new_email, email_in_use_email(self.settings.app_name, settings=self.settings))
            return
        code = new_email_code()
        self.db.add(
            EmailCode(
                email=new_email,
                purpose="change_email",
                user_id=user.id,
                code_hash=hash_code(self.settings, new_email, self._change_purpose(user.id), code),
                expires_at=utcnow() + timedelta(minutes=self.settings.email_code_ttl_minutes),
            )
        )
        await self.db.commit()
        ttl = self.settings.email_code_ttl_minutes
        await self._deliver(
            new_email, code_email(self.settings.app_name, "change_email", code, ttl, settings=self.settings)
        )

    async def confirm_email_change(self, user: User, current_session_id: uuid.UUID, new_email: str, code: str) -> User:
        row = await self.db.scalar(
            select(EmailCode)
            .where(
                EmailCode.email == new_email,
                EmailCode.purpose == "change_email",
                EmailCode.user_id == user.id,
                EmailCode.consumed_at.is_(None),
            )
            .order_by(EmailCode.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if row is None or row.expires_at <= utcnow() or row.attempts >= self.settings.email_code_max_attempts:
            raise InvalidCode()
        if row.code_hash != hash_code(self.settings, new_email, self._change_purpose(user.id), code):
            row.attempts += 1
            await self.db.commit()
            raise InvalidCode()
        old_email = user.email
        try:
            await self.db.execute(
                update(User)
                .where(User.id == user.id)
                .values(
                    email=new_email,
                    email_verified_at=func.clock_timestamp(),
                    profile_version=User.profile_version + 1,
                    updated_at=func.clock_timestamp(),
                )
                .execution_options(synchronize_session=False)
            )
        except IntegrityError as error:  # someone registered the address after the code was sent
            await self.db.rollback()
            raise Conflict("That email address is no longer available.", code="email_unavailable") from error
        # No code for either address survives: an old reset code must not reach the account
        # again, and nobody else's pending move to the new address can complete now.
        await self.db.execute(
            delete(EmailCode).where(
                or_(EmailCode.email == old_email, EmailCode.email == new_email, EmailCode.user_id == user.id)
            )
        )
        await self.db.execute(
            delete(AuthVerification).where(
                AuthVerification.identifier.in_(otp_identifiers(old_email) + otp_identifiers(new_email))
            )
        )
        await self.revoke_other_sessions(user.id, current_session_id, commit=False)
        await self.db.commit()
        await self.db.refresh(user)
        # After the commit: the change stands even when the notice cannot be sent right now.
        notice = email_changed_email(self.settings.app_name, new_email, settings=self.settings)
        try:
            await self.email.send(old_email, notice.subject, notice.body, html=notice.html)
        except Exception as error:  # noqa: BLE001
            log.error("email change notice failed", extra={"error_type": type(error).__name__})
        return user

    async def delete_account(self, user: User, session: AuthSession, password: str | None) -> None:
        await self.reauthenticate(user, session, password)
        address = user.email
        await self.db.execute(delete(User).where(User.id == user.id))  # cascades to all user data
        # Codes are keyed by address, not by user, so the cascade misses them. A reset code left
        # behind would still work on a new account registered with the same address.
        await self.db.execute(delete(EmailCode).where(EmailCode.email == address))
        await self.db.execute(delete(AuthVerification).where(AuthVerification.identifier.in_(otp_identifiers(address))))
        await self.db.commit()
        # After the commit, and best effort: the account is gone whether or not this arrives.
        notice = account_deleted_email(self.settings.app_name, settings=self.settings)
        try:
            await self.email.send(address, notice.subject, notice.body, html=notice.html)
        except Exception as error:  # noqa: BLE001
            log.error("account deleted notice failed", extra={"error_type": type(error).__name__})

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
