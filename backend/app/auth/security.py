"""Password hashing (argon2id), session tokens and one-time email codes."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.settings import Settings

# argon2id costs 64 MiB and a few hundred ms per call: at most this many run at once, so a burst
# of password checks queues instead of taking the host's memory and every worker thread.
CONCURRENT_HASHES = 2


class Passwords:
    """argon2id hashing, run off the event loop (it is deliberately CPU/memory heavy). The web
    app's Better Auth writes and checks the same PHC strings (frontend/apps/app/src/lib/auth)."""

    def __init__(self, settings: Settings) -> None:
        self._hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_kib,
            parallelism=settings.argon2_parallelism,
        )
        # Verified against when an email is unknown, so a missing account costs the
        # same time as a wrong password (no account enumeration by timing).
        self._dummy_hash = self._hasher.hash(secrets.token_hex(16))
        self._slots = asyncio.Semaphore(CONCURRENT_HASHES)

    async def hash(self, password: str) -> str:
        async with self._slots:
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

        async with self._slots:
            return await asyncio.to_thread(_verify)


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
