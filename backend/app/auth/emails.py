"""Outgoing email: SMTP (Mailpit locally) or the Ollastack Agent Mail API; memory in tests."""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

import httpx

from app.logging import get_logger
from app.settings import Settings

log = get_logger("app.email")


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _send_sync(self, message: EmailMessage) -> None:
        s = self.settings
        smtp_cls = smtplib.SMTP_SSL if s.smtp_ssl else smtplib.SMTP
        with smtp_cls(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_starttls and not s.smtp_ssl:
                smtp.starttls()
            if s.smtp_username:
                smtp.login(s.smtp_username, s.smtp_password.get_secret_value())
            smtp.send_message(message)

    async def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        await asyncio.to_thread(self._send_sync, message)


class EmailDeliveryError(Exception):
    """A provider refused or failed a message. The text never contains the token or the recipient.

    `definite` is False when the message may have been delivered anyway (the provider timed out
    after receiving it): the outbox then never sends it again (app/notifications/sender.py)."""

    def __init__(self, message: str, *, definite: bool = True) -> None:
        super().__init__(message)
        self.definite = definite


class OllastackEmailSender:
    """Sends from one Ollastack Agent Mail mailbox over HTTPS (EMAIL_BACKEND=ollastack).

    The mailbox decides the sender address and display name; EMAIL_FROM is not used.
    """

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = http_client

    async def send(self, to: str, subject: str, body: str) -> None:
        s = self.settings
        url = f"{s.ollastack_base_url.rstrip('/')}/api/mailboxes/{s.ollastack_mailbox_id}/send"
        headers = {"Authorization": f"Bearer {s.ollastack_token.get_secret_value()}"}
        client = self._client or httpx.AsyncClient(timeout=15)
        try:
            response = await client.post(url, json={"to": to, "subject": subject, "text": body}, headers=headers)
        except httpx.HTTPError as error:
            # A connection that never opened sent nothing; a read or write that timed out may have.
            sent_maybe = isinstance(error, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError))
            raise EmailDeliveryError(
                f"ollastack unreachable ({type(error).__name__})", definite=not sent_maybe
            ) from None
        finally:
            if self._client is None:
                await client.aclose()
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if response.status_code >= 300 or not payload.get("success"):
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            log.warning("ollastack send rejected", extra={"status": response.status_code, "error_code": code})
            raise EmailDeliveryError(
                f"ollastack rejected the message (HTTP {response.status_code}, {code or 'no code'})"
            )
        status = (payload.get("data") or {}).get("deliveryStatus")
        if status in ("failed", "bounced", "rejected"):
            log.warning("ollastack delivery failed", extra={"delivery_status": status})
            raise EmailDeliveryError(f"ollastack delivery status {status}")


@dataclass
class MemoryEmailSender:
    """Keeps sent mail in memory. Tests read codes from `outbox`."""

    outbox: list[dict] = field(default_factory=list)

    async def send(self, to: str, subject: str, body: str) -> None:
        self.outbox.append({"to": to, "subject": subject, "body": body})


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.email_backend == "memory":
        return MemoryEmailSender()
    if settings.email_backend == "ollastack":
        return OllastackEmailSender(settings)
    return SmtpEmailSender(settings)


def code_email(app_name: str, purpose: str, code: str, ttl_minutes: int) -> tuple[str, str]:
    # Every purpose is named: an unknown one must fail loudly, not borrow another's wording.
    if purpose == "verify_email":
        subject = f"Your {app_name} verification code"
        intro = f"Use this code to verify your email address for {app_name}:"
    elif purpose == "reset_password":
        subject = f"Your {app_name} password reset code"
        intro = f"Use this code to reset your {app_name} password:"
    elif purpose == "change_email":
        subject = f"Your {app_name} email change code"
        intro = f"Use this code to make this address the email of your {app_name} account:"
    elif purpose == "sign_in":
        subject = f"Your {app_name} sign-in code"
        intro = f"Use this code to sign in to {app_name} (or to create your account, if you are new):"
    else:
        raise ValueError(f"no email text for code purpose {purpose!r}")
    body = (
        f"{intro}\n\n    {code}\n\n"
        f"The code expires in {ttl_minutes} minutes. If you did not request it, ignore this email."
    )
    return subject, body


def mask_email(address: str) -> str:
    """`ab***@example.com`: enough for the owner to recognise, not enough to copy."""
    local, _, domain = address.partition("@")
    return f"{local[:2]}***@{domain}"


def email_in_use_email(app_name: str) -> tuple[str, str]:
    return (
        f"Someone tried to use your email address on {app_name}",
        f"Another {app_name} account asked to change its email to this address, which already belongs "
        "to your account. Nothing was changed. If you did not expect this, you can ignore this email.",
    )


def email_changed_email(app_name: str, new_address: str) -> tuple[str, str]:
    return (
        f"The email address of your {app_name} account was changed",
        f"The email address of your {app_name} account was changed to {mask_email(new_address)}, and "
        "every other device was signed out.\n\n"
        "If you did not do this, someone knows your password: reset it from the sign-in page with the "
        "new address, or contact support from the app.",
    )


def account_deleted_email(app_name: str) -> tuple[str, str]:
    return (
        f"Your {app_name} account was deleted",
        f"Your {app_name} account and everything in it (chats, files, learning history) were deleted "
        "just now, and every device was signed out.\n\n"
        "If you did not do this, someone had access to your account: contact support, and check "
        "the security of this email address.",
    )
