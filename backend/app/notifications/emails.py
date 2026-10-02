"""The text of every notification email: plain text, short, and never anything the reader
did not already know about their own account. No IP addresses (only a device label)."""

from __future__ import annotations


def _footer(settings_url: str, unsubscribe_url: str | None) -> str:
    lines = ["", "--", f"Choose which emails you get: {settings_url}"]  # a URL, or "PadhAI Settings"
    if unsubscribe_url:
        lines.append(f"Stop emails like this one: {unsubscribe_url}")
    return "\n".join(lines)


def sign_in_alert(app: str, device: str, when: str, settings_url: str, unsubscribe_url: str | None) -> tuple[str, str]:
    return (
        f"New sign-in to your {app} account",
        f"Your {app} account was signed in to from a new device.\n\n"
        f"    Device: {device}\n    When:   {when}\n\n"
        "If this was you, there is nothing to do.\n"
        f"If it wasn't, change your password now and sign out the other devices in {app}'s "
        "Settings, under Privacy & Security." + _footer(settings_url, unsubscribe_url),
    )


def password_changed(app: str, when: str, settings_url: str) -> tuple[str, str]:
    return (
        f"Your {app} password was changed",
        f"The password of your {app} account was changed ({when}), and every other device was "
        "signed out.\n\n"
        "If you didn't do this, reset your password from the sign-in page now." + _footer(settings_url, None),
    )


def google_linked(app: str, when: str, settings_url: str) -> tuple[str, str]:
    return (
        f"Google sign-in was added to your {app} account",
        f"Your {app} account can now be signed in to with a Google account ({when}).\n\n"
        f"If you didn't do this, disconnect Google in {app}'s Settings, under Privacy & Security, "
        "and change your password." + _footer(settings_url, None),
    )


def two_factor(app: str, on: bool, when: str, settings_url: str) -> tuple[str, str]:
    if on:
        return (
            f"Two-step sign-in was turned on for your {app} account",
            f"Signing in to your {app} account now also needs a code from an authenticator app ({when}).\n\n"
            'If you didn\'t do this, reset your password with "Forgot password?" on the sign-in page '
            "right away, then contact us: someone else may control your account." + _footer(settings_url, None),
        )
    return (
        f"Two-step sign-in was turned off for your {app} account",
        f"Signing in to your {app} account no longer needs an authenticator code ({when}).\n\n"
        f"If you didn't do this, change your password and turn two-step sign-in back on in {app}'s "
        "Settings, under Privacy & Security." + _footer(settings_url, None),
    )


def daily_reminder(app: str, app_url: str, settings_url: str, unsubscribe_url: str) -> tuple[str, str]:
    return (
        f"Time for today's {app} session",
        f"You asked {app} to remind you at this time. A few minutes today keeps things moving.\n\n"
        f"Open {app}: {app_url}" + _footer(settings_url, unsubscribe_url),
    )


def streak_warning(
    app: str, streak_days: int, app_url: str, settings_url: str, unsubscribe_url: str
) -> tuple[str, str]:
    return (
        f"Keep your {streak_days}-day streak going",
        f"You've been active in {app} for {streak_days} days in a row. There's still time to keep "
        f"the streak alive today.\n\nOpen {app}: {app_url}" + _footer(settings_url, unsubscribe_url),
    )


def weekly_summary(
    app: str,
    week: str,
    active_minutes: int,
    questions: int,
    active_days: int,
    app_url: str,
    settings_url: str,
    unsubscribe_url: str,
) -> tuple[str, str]:
    return (
        f"Your {app} week: {week}",
        f"Here is your week in {app} ({week}):\n\n"
        f"    Active time:  about {active_minutes} min\n"
        f"    Questions:    {questions}\n"
        f"    Active days:  {active_days} of 7\n\n"
        "Active time counts the minutes you spent using the app, not all of your studying.\n\n"
        f"Open {app}: {app_url}" + _footer(settings_url, unsubscribe_url),
    )


def support_forward(
    app: str, kind: str, subject: str, message: str, reply_to: str, request_id: str, context: str
) -> tuple[str, str]:
    return (
        f"[{app} support] {kind}: {subject}",
        f"A support request from {reply_to} (request {request_id}).\n\n"
        f"Kind:    {kind}\nSubject: {subject}\nContext: {context}\n\n{message}\n",
    )
