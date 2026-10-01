"""Who is calling. Identity comes ONLY from a server-verified session token."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.emails import EmailSender
from app.auth.security import Passwords, hash_token
from app.auth.service import AuthService, ClientInfo, utcnow
from app.db.models import AuthSession, User
from app.db.session import get_session
from app.errors import EmailNotVerified, Unauthorized
from app.logging import user_id_var
from app.settings import Settings

# Move last_seen_at at most this often, not on every request.
SLIDE_EVERY = timedelta(hours=1)


@dataclass
class Principal:
    user: User
    session: AuthSession


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def client_info(request: Request) -> ClientInfo:
    settings: Settings = request.app.state.settings
    ip = request.client.host if request.client else None
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        ip = forwarded.split(",")[0].strip() or ip
    return ClientInfo(ip=ip, user_agent=request.headers.get("user-agent"))


def get_auth_service(request: Request, db: AsyncSession = Depends(get_session)) -> AuthService:
    state = request.app.state
    passwords: Passwords = state.passwords
    email: EmailSender = state.email_sender
    return AuthService(db, state.settings, passwords, email)


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized()
    return token.strip()


async def get_principal(request: Request, db: AsyncSession = Depends(get_session)) -> Principal:
    """The session is found by the SHA-256 of its token: Better Auth's sessions (a trigger
    computes the hash, 0012) and older ones alike, so a release and its predecessor both accept
    the sessions in use while a deploy or a rollback swaps the halves. Better Auth owns the
    expiry and refreshes it with the cookie; here only last_seen_at moves."""
    token = _bearer(request)
    row = (
        await db.execute(
            select(AuthSession, User)
            .join(User, User.id == AuthSession.user_id)
            .where(AuthSession.token_hash == hash_token(token))
        )
    ).first()
    now = utcnow()
    if row is None or row.AuthSession.expires_at <= now:
        raise Unauthorized()
    session, user = row.AuthSession, row.User
    if not user.email_verified:
        raise EmailNotVerified()
    if now - session.last_seen_at > SLIDE_EVERY:
        await db.execute(update(AuthSession).where(AuthSession.id == session.id).values(last_seen_at=now))
        await db.commit()
    user_id_var.set(str(user.id))
    return Principal(user=user, session=session)
