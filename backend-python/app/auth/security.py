"""Password hashing (argon2id), session tokens and one-time email codes."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.settings import Settings


class Passwords:
    """argon2id hashing, run off the event loop (it is deliberately CPU/memory heavy)."""

    def __init__(self, settings: Settings) -> None:
        self._hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_kib,
            parallelism=settings.argon2_parallelism,
        )
        # Verified against when an email is unknown, so a missing account costs the
        # same time as a wrong password (no account enumeration by timing).
        self._dummy_hash = self._hasher.hash(secrets.token_hex(16))

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._hasher.hash, password)

    async def verify(self, password_hash: str | None, password: str) -> tuple[bool, bool]:
        """Returns (valid, needs_rehash)."""
        target = password_hash or self._dummy_hash

        def _verify() -> tuple[bool, bool]:
            try:
                self._hasher.verify(target, password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False, False
            return password_hash is not None, self._hasher.check_needs_rehash(target)

        return await asyncio.to_thread(_verify)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_email_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(settings: Settings, email: str, purpose: str, code: str) -> str:
    """HMAC, keyed by SECRET_KEY: a six-digit code is too small a space to store as a bare hash."""
    message = f"{email.lower()}|{purpose}|{code}".encode()
    return hmac.new(settings.secret_key.get_secret_value().encode(), message, hashlib.sha256).hexdigest()


def hash_key(value: str) -> str:
    return hashlib.sha256(value.lower().encode()).hexdigest()
