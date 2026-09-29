"""Account and session logic. All state lives in PostgreSQL.

Anti-enumeration: sign-up, resend and forgot-password always answer 202, and a
login for an unknown email costs the same argon2 time as a wrong password.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.avatar import ProcessedAvatar
from app.auth.devices import device_label
from app.auth.emails import EmailSender, code_email, email_changed_email, email_in_use_email
from app.auth.security import Passwords, hash_code, hash_key, hash_token, new_email_code, new_session_token
from app.db.models import AuthAttempt, AuthSession, EmailCode, User, UserAvatar, UserSettings
from app.errors import (
    Conflict,
    EmailNotVerified,
    InvalidCode,
    InvalidCredentials,
    NotFound,
    RateLimited,
    ServiceUnavailable,
    ValidationFailed,
    VersionConflict,
)
from app.logging import get_logger
from app.notifications.alerts import queue_password_changed, queue_sign_in_alert
from app.settings import Settings

log = get_logger("app.auth")

MAX_PREFERENCES_BYTES = 4096
# File Library uploads per student (app/files): per AUTH_WINDOW_MINUTES, and per day.
FILES_UPLOADS_PER_WINDOW = 20
FILES_UPLOADS_PER_DAY = 30


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

    async def _record_attempt(self, scope: str, key: str) -> None:
        self.db.add(AuthAttempt(scope=scope, key_hash=hash_key(key)))

    async def _throttle(self, scope: str, key: str | None, limit: int, record: bool = True) -> None:
        if not key:
            return
        if await self._count_attempts(scope, key) >= limit:
            raise RateLimited()
        if record:
            await self._record_attempt(scope, key)

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
        new_device = not await self._device_known(user.id, client.user_agent)
        issued = await self._issue_session(user, client)
        if new_device:
            await queue_sign_in_alert(self.db, self.settings, user, device_label(client.user_agent), utcnow())
        await self.db.commit()
        return issued

    async def _device_known(self, user_id: uuid.UUID, user_agent: str | None) -> bool:
        """Whether a live session of this account already signed in with the same kind of
        device ("Chrome on Windows"): the test for a sign-in alert."""
        label = device_label(user_agent)
        agents = await self.db.scalars(
            select(AuthSession.user_agent).where(AuthSession.user_id == user_id, AuthSession.expires_at > utcnow())
        )
        return any(device_label(agent) == label for agent in agents)

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
        user.password_changed_at = user.updated_at
        await self.db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        issued = await self._issue_session(user, client)
        await queue_password_changed(self.db, self.settings, user, user.updated_at)
        await self.db.commit()
        return issued

    async def change_password(self, user: User, session_id: uuid.UUID, current: str, new: str) -> None:
        valid, _ = await self.passwords.verify(user.password_hash, current)
        if not valid:
            raise InvalidCredentials("The current password is incorrect.")
        user.password_hash = await self.passwords.hash(new)
        user.updated_at = utcnow()
        user.password_changed_at = user.updated_at
        await self.revoke_other_sessions(user.id, session_id, commit=False)
        await queue_password_changed(self.db, self.settings, user, user.updated_at)
        await self.db.commit()

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

    async def request_email_change(self, user: User, new_email: str, password: str) -> None:
        """Answers 202 whatever the address. If it is free, a code goes to it; if another account
        has it, a notice goes to it instead. Either way exactly one email is sent, so the caller
        cannot tell which happened."""
        if new_email.lower() == user.email.lower():
            raise ValidationFailed(
                "That is already your email address.", fields=[{"field": "newEmail", "reason": "unchanged"}]
            )
        await self._throttle("login_fail", user.email, self.settings.login_failures_per_email, record=False)
        await self._throttle("email_change_user", str(user.id), self.settings.email_change_requests_per_user)
        await self._throttle("code_email", new_email, self.settings.code_requests_per_email)
        valid, _ = await self.passwords.verify(user.password_hash, password)
        if not valid:
            await self._record_attempt("login_fail", user.email)
            await self.db.commit()
            raise InvalidCredentials("The password is incorrect.")
        # Only the latest request can be confirmed.
        await self.db.execute(
            delete(EmailCode).where(EmailCode.purpose == "change_email", EmailCode.user_id == user.id)
        )
        if await self._user_by_email(new_email) is not None:
            subject, body = email_in_use_email(self.settings.app_name)
            await self._deliver(new_email, subject, body)
            await self.db.commit()
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
        subject, body = code_email(self.settings.app_name, "change_email", code, self.settings.email_code_ttl_minutes)
        await self._deliver(new_email, subject, body)
        await self.db.commit()

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
        await self.revoke_other_sessions(user.id, current_session_id, commit=False)
        await self.db.commit()
        await self.db.refresh(user)
        # After the commit: the change stands even when the notice cannot be sent right now.
        subject, body = email_changed_email(self.settings.app_name, new_email)
        try:
            await self.email.send(old_email, subject, body)
        except Exception as error:  # noqa: BLE001
            log.error("email change notice failed", extra={"error_type": type(error).__name__})
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
