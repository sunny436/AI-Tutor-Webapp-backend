"""What the web app's Better Auth (frontend/apps/app/src/lib/auth) asks the API to do after it
acts: send a sign-in or reset code, and raise the security notices. The API keeps the one email
sender and its templates (app/auth/emails.py, app/notifications/emails.py).

Loopback only (the API listens on 127.0.0.1, and the BFF allowlist never includes /internal),
behind AUTH_INTERNAL_TOKEN, and outside the public contract. Nothing is taken on trust, so a
leaked token cannot mail arbitrary people or forge alerts:
- a code is emailed only when its hash matches the verification row Better Auth wrote for that
  address moments ago (storeOTP "hashed": base64url(SHA-256(code)), "<type>-otp-<email>");
- an event counts only when the rows it names exist and are fresh.
Emails go out after the commit, from a background task: no pooled connection waits on the mail
provider. Each event leaves one JSON log line (ids and kinds only: no address, code or IP).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from pydantic import EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.devices import device_label
from app.auth.emails import EmailSender, code_email, welcome_email
from app.auth.service import utcnow
from app.db.models import AuthAccount, AuthSession, AuthTwoFactor, AuthVerification, User
from app.db.session import get_session
from app.email_html import Email
from app.errors import NotFound
from app.logging import get_logger
from app.notifications.alerts import google_linked_alert, password_changed_alert, sign_in_alert, two_factor_alert
from app.schemas import RequestModel

log = get_logger("app.auth.internal")
router = APIRouter(prefix="/internal/auth", include_in_schema=False)

# How recent a row must be for the request that names it to count.
FRESH = timedelta(minutes=2)
# The account's only session, made this soon after it, is the sign-up itself (by code or Google):
# the same request creates both.
SIGN_UP = timedelta(seconds=10)
CODE_PURPOSE = {"sign-in": "sign_in", "forget-password": "reset_password"}
CODE_MINUTES = 15  # Better Auth's emailOTP expiresIn (frontend/apps/app/src/lib/auth/config.ts)


def require_internal(request: Request) -> None:
    expected = request.app.state.settings.auth_internal_token.get_secret_value()
    given = request.headers.get("x-internal-token", "")
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        raise NotFound()


class CodeIn(RequestModel):
    email: EmailStr
    type: Literal["sign-in", "forget-password"]
    otp: str = Field(pattern=r"^\d{6}$")


class EventIn(RequestModel):
    kind: Literal["sign_in", "password_changed", "password_reset", "google_linked", "two_factor_on", "two_factor_off"]
    user_id: uuid.UUID
    session_id: uuid.UUID | None = None


def code_hash(otp: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(otp.encode()).digest()).rstrip(b"=").decode()


async def _send(sender: EmailSender, to: str, email: Email, what: str) -> None:
    try:
        await sender.send(to, email.subject, email.body, html=email.html)
    except Exception as error:  # noqa: BLE001 - logged; the account change stands either way
        log.error("auth email failed", extra={"email_kind": what, "error_type": type(error).__name__})


@router.post("/code", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_internal)])
async def send_code(
    body: CodeIn, request: Request, background: BackgroundTasks, db: AsyncSession = Depends(get_session)
) -> Response:
    email = body.email.lower()
    values = (
        await db.scalars(
            select(AuthVerification.value).where(
                AuthVerification.identifier == f"{body.type}-otp-{email}",
                AuthVerification.created_at > utcnow() - FRESH,
            )
        )
    ).all()
    await db.commit()
    expected = code_hash(body.otp)
    if any(hmac.compare_digest(value.rpartition(":")[0], expected) for value in values):
        settings = request.app.state.settings
        message = code_email(settings.app_name, CODE_PURPOSE[body.type], body.otp, CODE_MINUTES, settings=settings)
        background.add_task(_send, request.app.state.email_sender, email, message, CODE_PURPOSE[body.type])
        log.info("auth code queued", extra={"code_type": body.type})
    else:
        log.warning("auth code refused: no matching fresh code", extra={"code_type": body.type})
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/events", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_internal)])
async def auth_event(
    body: EventIn, request: Request, background: BackgroundTasks, db: AsyncSession = Depends(get_session)
) -> Response:
    settings = request.app.state.settings
    now = utcnow()
    user = await db.get(User, body.user_id)
    email: Email | None = None
    what = body.kind
    counted = False
    if user is not None and body.kind == "sign_in" and body.session_id is not None:
        session = await db.get(AuthSession, body.session_id)
        if session is not None and session.user_id == user.id and session.created_at > now - FRESH:
            counted = True
            label = device_label(session.user_agent)
            others = list(
                await db.scalars(
                    select(AuthSession.user_agent).where(
                        AuthSession.user_id == user.id, AuthSession.id != session.id, AuthSession.expires_at > now
                    )
                )
            )
            # A session created alongside the account is treated as sign-up. Delivery is best effort:
            # a delayed event can miss it, and a replay can send the welcome again.
            sign_up = not others and session.created_at <= user.created_at + SIGN_UP
            if sign_up:
                email, what = welcome_email(settings.app_name, user.display_name, settings=settings), "welcome"
            elif not any(device_label(agent) == label for agent in others):
                email = await sign_in_alert(db, settings, user, label, now)
    elif user is not None and body.kind in ("password_changed", "password_reset"):
        changed = await db.scalar(
            select(AuthAccount.updated_at).where(
                AuthAccount.user_id == user.id, AuthAccount.provider_id == "credential"
            )
        )
        if changed is not None and changed > now - FRESH:
            counted = True
            email = await password_changed_alert(db, settings, user, now, reset=body.kind == "password_reset")
    elif user is not None and body.kind == "google_linked":
        linked = await db.scalar(
            select(AuthAccount.created_at).where(AuthAccount.user_id == user.id, AuthAccount.provider_id == "google")
        )
        # Linked moments ago to an account that existed before (not a first sign-up with Google).
        if linked is not None and linked > now - FRESH and user.created_at < linked - FRESH:
            counted = True
            email = await google_linked_alert(db, settings, user, now)
    elif user is not None and body.kind in ("two_factor_on", "two_factor_off"):
        # Better Auth moves users.updated_at when it flips the flag; the row says which way.
        on = body.kind == "two_factor_on"
        verified = await db.scalar(select(AuthTwoFactor.verified).where(AuthTwoFactor.user_id == user.id))
        if user.updated_at > now - FRESH and user.two_factor_enabled == on and (verified is True) == on:
            counted = True
            email = await two_factor_alert(db, settings, user, on, now)
    await db.commit()
    log.info(
        "auth event",
        extra={
            "auth_event": body.kind,
            "user_id": str(body.user_id),
            "counted": counted,
            "emailed": email is not None,
            "email_kind": what if email is not None else None,
        },
    )
    if email is not None and user is not None:
        background.add_task(_send, request.app.state.email_sender, user.email, email, what)
    return Response(status_code=status.HTTP_202_ACCEPTED)
