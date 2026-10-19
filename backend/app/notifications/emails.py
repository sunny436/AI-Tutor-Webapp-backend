"""The text of every notification email: plain text, short, and never anything the reader
did not already know about their own account. No IP addresses (only a device label).

Each also has an HTML part built from the same values (app/email_html.py). Reminders keep
only their text for now: the outbox stores a subject and a body (app/notifications/outbox.py)."""

from __future__ import annotations

from app.email_html import (
    SUCCESS,
    TEXT,
    WARNING,
    Email,
    alert,
    app_link,
    bdi,
    button,
    caption,
    checked_url,
    clean_text,
    details,
    document,
    first_name,
    heading,
    hero,
    join,
    link,
    paragraph,
    render_html,
    stats,
    streak_badge,
    strong,
)
from app.settings import Settings

REQUIRED = "This is a required security email about your PadhAI account."


def _footer(label: str, url: str | None, unsubscribe_url: str | None = None) -> str:
    lines = ["", "--"]
    if url:
        lines.append(f"{label}: {url}")
    if unsubscribe_url:
        lines.append(f"Stop emails like this one: {unsubscribe_url}")
    return "\n".join(lines)


def _optional_footer(settings_url: str, unsubscribe_url: str | None) -> str:
    return _footer("Choose which emails you get", settings_url, unsubscribe_url)


def _security_footer(settings_url: str) -> str:
    return _footer("Review Privacy & Security", settings_url)


def _hello(name: str | None) -> str:
    return f"Hi {first_name(name) or 'there'},"


def _hello_html(name: str | None):
    found = first_name(name)
    return join("Hi ", bdi(found), ",") if found else "Hi there,"


def sign_in_alert(
    app: str,
    device: str,
    when: str,
    settings_url: str,
    unsubscribe_url: str | None,
    *,
    settings: Settings | None = None,
) -> Email:
    subject = f"New sign-in to your {app} account"
    device = clean_text(device)
    body = (
        f"Your {app} account was signed in to from a new device.\n\n"
        f"    Device: {device}\n    When:   {when}\n\n"
        "If this was you, there is nothing to do.\n"
        f"If it wasn't, change your password now and sign out the other devices in {app}'s "
        "Settings, under Privacy & Security." + _optional_footer(settings_url, unsubscribe_url)
    )

    def build() -> str:
        return document(
            settings,
            title=subject,
            preview=f"{device}, {when}. If this was you, there is nothing to do.",
            blocks=[
                heading("New sign-in to your account"),
                paragraph(
                    f"Your {app} account was signed in to from a new device. If this was you, there is nothing to do."
                ),
                details([("Device", device), ("When", when)]),
                alert(
                    "Not you?",
                    f"Change your password now, and sign out the other devices in {app}'s Settings, "
                    "under Privacy & Security.",
                    action=("Review your devices", app_link(settings, "privacy")),
                ),
            ],
            note="You get these emails because sign-in alerts are on.",
            settings_url=app_link(settings, "notifications"),
            unsubscribe_url=checked_url(settings, unsubscribe_url),
        )

    return Email(subject, body, render_html("sign_in_alert", build))


def password_changed(
    app: str, when: str, settings_url: str, *, reset: bool = False, settings: Settings | None = None
) -> Email:
    subject = f"Your {app} password was changed"
    how, signed_out = (
        ("reset with a code sent to this address", "every device")
        if reset
        else ("changed in Settings", "every other device")
    )
    what = f"The password of your {app} account was {how}, and {signed_out} was signed out."
    body = (
        f"{what[:-1]} ({when}).\n\nIf you didn't do this, reset your password from the sign-in page now."
        + _security_footer(settings_url)
    )

    def build() -> str:
        return document(
            settings,
            title=subject,
            preview=f"{when}. If you didn't do this, reset your password now.",
            blocks=[
                heading("Your password was reset" if reset else "Your password was changed"),
                paragraph(what),
                details([("When", when)]),
                alert(
                    "Didn't do this?",
                    'Reset your password from the sign-in page now: choose "Forgot password?".',
                    action=("Go to sign-in", app_link(settings, "login")),
                ),
            ],
            note=REQUIRED,
        )

    return Email(subject, body, render_html("password_changed", build))


def google_linked(app: str, when: str, settings_url: str, *, settings: Settings | None = None) -> Email:
    subject = f"Google sign-in was added to your {app} account"
    not_you = f"disconnect Google in {app}'s Settings, under Privacy & Security, and change your password."
    body = (
        f"Your {app} account can now be signed in to with a Google account ({when}).\n\n"
        f"If you didn't do this, {not_you}" + _security_footer(settings_url)
    )

    def build() -> str:
        privacy = app_link(settings, "privacy")
        return document(
            settings,
            title=subject,
            preview=f"{when}. If you didn't do this, disconnect Google now.",
            blocks=[
                heading("Google sign-in was added"),
                paragraph(f"Your {app} account can now be signed in to with a Google account."),
                details([("When", when)]),
                paragraph(
                    join(
                        "You can see and remove the ways you sign in under ", link("Privacy & Security", privacy), "."
                    ),
                    top=20,
                    size=14,
                ),
                alert("Didn't do this?", f"Then {not_you}", action=("Review how you sign in", privacy)),
            ],
            note=REQUIRED,
        )

    return Email(subject, body, render_html("google_linked", build))


def two_factor(app: str, on: bool, when: str, settings_url: str, *, settings: Settings | None = None) -> Email:
    if on:
        subject = f"Two-step sign-in was turned on for your {app} account"
        now = f"Signing in to your {app} account now also needs a code from an authenticator app"
        not_you = (
            'reset your password with "Forgot password?" on the sign-in page right away, then contact us: '
            "someone else may control your account."
        )
        title, color, action = "Two-step sign-in is on", SUCCESS, ("Go to sign-in", app_link(settings, "login"))
        explain = f"{now}, every time and every way you sign in."
    else:
        subject = f"Two-step sign-in was turned off for your {app} account"
        now = f"Signing in to your {app} account no longer needs an authenticator code"
        not_you = (
            f"change your password and turn two-step sign-in back on in {app}'s Settings, under Privacy & Security."
        )
        title, color, action = (
            "Two-step sign-in is off",
            WARNING,
            ("Review your security", app_link(settings, "privacy")),
        )
        explain = f"{now}."
    body = f"{now} ({when}).\n\nIf you didn't do this, {not_you}" + _security_footer(settings_url)

    def build() -> str:
        return document(
            settings,
            title=subject,
            preview=f"{when}. If you didn't do this, act now.",
            blocks=[
                alert(title, explain, color=color, title_color=TEXT, title_size=20, text_size=16),
                details([("When", when)]),
                alert("Didn't do this?", f"Then {not_you}", action=action),
            ],
            note=REQUIRED,
        )

    return Email(subject, body, render_html("two_factor_on" if on else "two_factor_off", build))


def _reminder_note(app: str, reminder: str) -> str:
    return f"You get this email because you turned on the {reminder} in {app}'s Settings."


def daily_reminder(
    app: str,
    app_url: str,
    settings_url: str,
    unsubscribe_url: str,
    *,
    name: str | None = None,
    settings: Settings | None = None,
) -> Email:
    subject = f"Time for today's {app} session"
    asked = f"You asked {app} to remind you at this time. A few minutes today keeps things moving."
    body = f"{_hello(name)}\n\n{asked}\n\nOpen {app}: {app_url}" + _optional_footer(settings_url, unsubscribe_url)

    def build() -> str:
        return document(
            settings,
            title=subject,
            preview=asked,
            blocks=[
                heading(_hello_html(name)),
                hero("Ready for today's session?", asked),
                button("Continue learning", app_link(settings, "home"), top=28, center=True),
            ],
            note=_reminder_note(app, "daily reminder"),
            settings_url=app_link(settings, "notifications"),
            unsubscribe_url=checked_url(settings, unsubscribe_url),
        )

    return Email(subject, body, render_html("daily_reminder", build))


def streak_warning(
    app: str,
    streak_days: int,
    app_url: str,
    settings_url: str,
    unsubscribe_url: str,
    *,
    time_left: str | None = None,
    name: str | None = None,
    settings: Settings | None = None,
) -> Email:
    subject = f"Keep your {streak_days}-day streak going"
    left = f" ({time_left} left)." if time_left else "."
    body = (
        f"{_hello(name)}\n\nYou've been active in {app} for {streak_days} days in a row. There's still time to keep "
        f"the streak alive today{left}\n\nOpen {app}: {app_url}" + _optional_footer(settings_url, unsubscribe_url)
    )

    def build() -> str:
        return document(
            settings,
            title=subject,
            preview=f"There's still time to keep the streak alive today{left}",
            blocks=[
                heading(_hello_html(name)),
                paragraph(strong("Keep your streak going."), top=8),
                streak_badge(streak_days),
                paragraph(
                    join(
                        f"You've been active in {app} for ",
                        strong(f"{streak_days} days"),
                        f" in a row. There's still time to keep the streak alive today{left}",
                    ),
                    top=28,
                ),
                button("Continue learning", app_link(settings, "home"), top=28, center=True),
            ],
            note=_reminder_note(app, "streak reminder"),
            settings_url=app_link(settings, "notifications"),
            unsubscribe_url=checked_url(settings, unsubscribe_url),
        )

    return Email(subject, body, render_html("streak_warning", build))


def weekly_summary(
    app: str,
    week: str,
    active_minutes: int,
    questions: int,
    active_days: int,
    app_url: str,
    settings_url: str,
    unsubscribe_url: str,
    *,
    name: str | None = None,
    settings: Settings | None = None,
) -> Email:
    subject = f"Your {app} week: {week}"
    note = "Active time counts the minutes you spent using the app, not all of your studying."
    body = (
        f"{_hello(name)}\n\nHere is your week in {app} ({week}):\n\n"
        f"    Active time:  about {active_minutes} min\n"
        f"    Questions:    {questions}\n"
        f"    Active days:  {active_days} of 7\n\n"
        f"{note}\n\n"
        f"Open {app}: {app_url}" + _optional_footer(settings_url, unsubscribe_url)
    )

    def build() -> str:
        return document(
            settings,
            title=subject,
            preview=f"About {active_minutes} min, {questions} questions and {active_days} active days.",
            blocks=[
                heading(f"Your week in {app}"),
                paragraph(join(_hello_html(name), " here is your week with your personal AI tutor.")),
                caption(week),
                stats(
                    [
                        ("Active time", f"about {active_minutes} min"),
                        ("Questions", str(questions)),
                        ("Active days", f"{active_days} of 7"),
                    ]
                ),
                paragraph(note, top=16, size=14),
                button("View your progress", app_link(settings, "progress"), top=28),
            ],
            note=_reminder_note(app, "weekly summary"),
            settings_url=app_link(settings, "notifications"),
            unsubscribe_url=checked_url(settings, unsubscribe_url),
        )

    return Email(subject, body, render_html("weekly_summary", build))


def support_forward(
    app: str, kind: str, subject: str, message: str, reply_to: str, request_id: str, context: str
) -> tuple[str, str]:
    return (
        f"[{app} support] {kind}: {subject}",
        f"A support request from {reply_to} (request {request_id}).\n\n"
        f"Kind:    {kind}\nSubject: {subject}\nContext: {context}\n\n{message}\n",
    )
