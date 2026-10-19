"""Outgoing email: SMTP (Mailpit locally) or the Ollastack Agent Mail API; memory in tests.

Every email is plain text, plus an HTML part when its builder made one (app/email_html.py):
SMTP sends both as multipart/alternative, Ollastack as `text` and `html`. A send without HTML
is exactly the request it always was."""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

import httpx

from app.email_html import (
    Email,
    alert,
    app_link,
    bdi,
    caution,
    code_box,
    details,
    document,
    first_name,
    footnote,
    heading,
    hero,
    join,
    paragraph,
    render_html,
    strong,
)
from app.email_html import (
    button as html_button,
)
from app.logging import get_logger
from app.settings import Settings

log = get_logger("app.email")

REQUIRED = "This is a required email about your PadhAI account."


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str, html: str | None = None) -> None: ...


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

    async def send(self, to: str, subject: str, body: str, html: str | None = None) -> None:
        message = EmailMessage()
        message["From"] = self.settings.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        if html:
            message.add_alternative(html, subtype="html")  # text first, HTML second
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

    async def send(self, to: str, subject: str, body: str, html: str | None = None) -> None:
        s = self.settings
        url = f"{s.ollastack_base_url.rstrip('/')}/api/mailboxes/{s.ollastack_mailbox_id}/send"
        headers = {"Authorization": f"Bearer {s.ollastack_token.get_secret_value()}"}
        message = {"to": to, "subject": subject, "text": body}
        if html:
            message["html"] = html
        client = self._client or httpx.AsyncClient(timeout=15)
        try:
            response = await client.post(url, json=message, headers=headers)
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

    async def send(self, to: str, subject: str, body: str, html: str | None = None) -> None:
        self.outbox.append({"to": to, "subject": subject, "body": body, "html": html})


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.email_backend == "memory":
        return MemoryEmailSender()
    if settings.email_backend == "ollastack":
        return OllastackEmailSender(settings)
    return SmtpEmailSender(settings)


def code_email(app_name: str, purpose: str, code: str, ttl_minutes: int, *, settings: Settings | None = None) -> Email:
    # Every purpose is named: an unknown one must fail loudly, not borrow another's wording.
    if purpose == "verify_email":
        subject = f"Your {app_name} verification code"
        intro = f"Use this code to verify your email address for {app_name}:"
        title = "Verify your email address"
        not_you = "If you didn't ask for this, you can ignore this email."
    elif purpose == "reset_password":
        subject = f"Your {app_name} password reset code"
        intro = f"Use this code to reset your {app_name} password:"
        title = "Reset your password"
        not_you = "If you didn't ask to reset your password, you can ignore this email: your password stays as it is."
    elif purpose == "change_email":
        subject = f"Your {app_name} email change code"
        intro = f"Use this code to make this address the email of your {app_name} account:"
        title = "Confirm your new email address"
        not_you = f"If you didn't ask to use this address for a {app_name} account, you can ignore this email."
    elif purpose == "sign_in":
        subject = f"Your {app_name} sign-in code"
        intro = f"Use this code to sign in to {app_name} (or to create your account, if you are new):"
        title = f"Sign in to {app_name}"
        not_you = (
            "If you didn't try to sign in, someone may have typed your address by mistake: you can ignore this email."
        )
    else:
        raise ValueError(f"no email text for code purpose {purpose!r}")
    body = f"{intro}\n\n    {code}\n\nThe code expires in {ttl_minutes} minutes. Don't share it with anyone.\n{not_you}"

    def build() -> str:
        return document(
            settings,
            title=subject,
            preview=f"The code expires in {ttl_minutes} minutes. Don't share it with anyone.",
            blocks=[
                heading(title),
                paragraph(join(intro.rstrip(":"), ". It expires in ", strong(f"{ttl_minutes} minutes"), ".")),
                code_box(code),
                caution("Don't share this code with anyone."),
                footnote(not_you),
            ],
            note=REQUIRED,
        )

    return Email(subject, body, render_html(f"code_{purpose}", build))


def mask_email(address: str) -> str:
    """`ab***@example.com`: enough for the owner to recognise, not enough to copy."""
    local, _, domain = address.partition("@")
    return f"{local[:2]}***@{domain}"


def email_in_use_email(app_name: str, *, settings: Settings | None = None) -> Email:
    subject = f"Someone tried to use your email address on {app_name}"
    asked = (
        f"Another {app_name} account asked to change its email to this address, which already belongs to your account."
    )
    # No digits anywhere in the text: it must never look like it carries a code.
    body = f"{asked} Nothing was changed. If you did not expect this, you can ignore this email."

    def build() -> str:
        return document(
            settings,
            title=subject,
            preview="Nothing was changed on your account.",
            blocks=[
                heading("Someone tried to use your email address"),
                paragraph(asked),
                paragraph("Nothing was changed on your account, and you don't need to do anything."),
                footnote("If you did not expect this, you can ignore this email."),
            ],
            note=REQUIRED,
        )

    return Email(subject, body, render_html("email_in_use", build))


def email_changed_email(
    app_name: str, new_address: str, *, when: str | None = None, settings: Settings | None = None
) -> Email:
    subject = f"The email address of your {app_name} account was changed"
    masked = mask_email(new_address)
    not_you = (
        f"If you did not do this, someone else may have access to your account: contact {app_name} support right away."
    )
    body = (
        f"The email address of your {app_name} account was changed to {masked}, and every other device "
        f"was signed out.{f' ({when})' if when else ''}\n\n{not_you}"
    )

    def build() -> str:
        return document(
            settings,
            title=subject,
            preview=f"It is now {masked}, and every other device was signed out.",
            blocks=[
                heading("Your email address was changed"),
                paragraph(
                    f"The email address of your {app_name} account was changed, and every other device was signed out."
                ),
                details([("New address", masked), ("When", when)]),
                alert(
                    "Didn't make this change?",
                    f"Someone else may have access to your account. Contact {app_name} support right away.",
                ),
            ],
            note=REQUIRED,
        )

    return Email(subject, body, render_html("email_changed", build))


def account_deleted_email(app_name: str, *, settings: Settings | None = None) -> Email:
    subject = f"Your {app_name} account was deleted"
    deleted = f"Your {app_name} account and its data (chats, files and learning history) were deleted from the app."
    backups = "Copies in backups are removed when those backups expire."
    not_you = "someone had access to your account: contact support, and check the security of this email address."
    body = f"{deleted} {backups} Every device was signed out.\n\nIf you did not do this, {not_you}"

    def build() -> str:
        return document(
            settings,
            title=subject,
            preview="Your account and its data were deleted from PadhAI.",
            blocks=[
                heading("Your account was deleted"),
                paragraph(join(deleted, " ", backups, " Every device was signed out.")),
                alert("Didn't do this?", f"Then {not_you}"),
                paragraph(f"Thank you for learning with {app_name}.", top=24),
            ],
            note=REQUIRED,
        )

    return Email(subject, body, render_html("account_deleted", build))


def welcome_email(app_name: str, display_name: str | None, *, settings: Settings | None = None) -> Email:
    """Sent best effort after the account's own first sign-in (app/auth/internal.py)."""
    subject = f"Welcome to {app_name}: your personal AI tutor"
    name = first_name(display_name)
    hello = f"Hi {name or 'there'},"
    glad = f"We're glad you're here. {app_name} is your personal AI tutor, made to help you learn at your own pace."
    how = (
        "Whether you need help with a concept, are revising for an exam or want to explore something new, "
        "your tutor can guide you step by step when you want."
    )
    start = app_link(settings, "home")
    manage = app_link(settings, "notifications")
    reason = f"You received this email because you just created a {app_name} account."
    body = (
        f"{hello}\n\nWelcome to {app_name}. Your Questions. Your Tutor. Your Way.\n\n{glad}\n\n{how}\n\n"
        + (f"Start learning: {start}" if start else f"Open {app_name} to start learning.")
        + f"\n\n--\n{reason}\nChoose which emails you get: {manage or f'{app_name} Settings'}"
    )

    def build() -> str:
        greeting = join("Hi ", bdi(name), ",") if name else "Hi there,"
        return document(
            settings,
            title=subject,
            preview="Your Questions. Your Tutor. Your Way.",
            blocks=[
                heading(greeting),
                hero(f"Welcome to {app_name}", "Your Questions. Your Tutor. Your Way."),
                paragraph(glad, top=28),
                paragraph(how),
                html_button("Start learning", start, top=28, center=True),
            ],
            note=reason,
            settings_url=manage,
        )

    return Email(subject, body, render_html("welcome", build))
