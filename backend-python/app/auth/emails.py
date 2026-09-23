"""Outgoing email. SMTP in every real environment (Mailpit locally); memory in tests."""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

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


@dataclass
class MemoryEmailSender:
    """Keeps sent mail in memory. Tests read codes from `outbox`."""

    outbox: list[dict] = field(default_factory=list)

    async def send(self, to: str, subject: str, body: str) -> None:
        self.outbox.append({"to": to, "subject": subject, "body": body})


def build_email_sender(settings: Settings) -> EmailSender:
    return MemoryEmailSender() if settings.email_backend == "memory" else SmtpEmailSender(settings)


def code_email(app_name: str, purpose: str, code: str, ttl_minutes: int) -> tuple[str, str]:
    if purpose == "verify_email":
        subject = f"Your {app_name} verification code"
        intro = f"Use this code to verify your email address for {app_name}:"
    else:
        subject = f"Your {app_name} password reset code"
        intro = f"Use this code to reset your {app_name} password:"
    body = (
        f"{intro}\n\n    {code}\n\n"
        f"The code expires in {ttl_minutes} minutes. If you did not request it, ignore this email."
    )
    return subject, body
