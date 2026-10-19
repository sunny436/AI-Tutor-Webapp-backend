"""Reminder emails, planned by the worker every minute and queued at most once per period.

Only for students who turned a reminder on and confirmed a time zone (users.timezone): a
reminder at the wrong hour is worse than none. Each has a window in the student's local time,
and a dedup key naming the student, the kind and the period, so however often the worker
runs, and even if two ran at once, a period gets one email:

- **daily_reminder**: in the hour from the preferred study time (the learner profile's, or
  18:00), and only if the student has not been active yet that day.
- **streak_warning**: 20:00–22:00 India time, when a learning streak of 2+ days would end
  tonight (app/progress/learning.py: the same streak the app shows).

Each reminder queued as an email is also added to the app's notifications, unless the student
turned in-app reminders off (app/notifications/inbox.py; the streak one shares its daily key
with the in-app streak reminder, so a day never gets two).
- **weekly_summary**: Mondays 08:00–12:00, about the previous week, if it had any activity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationPreferences, User
from app.email_html import Email, app_link
from app.learning.context import read_study_time
from app.notifications import emails
from app.notifications.alerts import settings_link
from app.notifications.inbox import in_app_reminders_on, notify
from app.notifications.outbox import DAILY_REMINDER, STREAK_WARNING, WEEKLY_SUMMARY, queue_email
from app.notifications.tokens import unsubscribe_url
from app.progress.activity import snapshot, zone_for
from app.progress.learning import LEARNING_ZONE, remaining_label, streak_state
from app.settings import Settings

DEFAULT_STUDY_TIME = time(18, 0)
DAILY_WINDOW = timedelta(hours=1)
STREAK_WINDOW = (time(20, 0), time(22, 0))
WEEKLY_WINDOW = (time(8, 0), time(12, 0))


@dataclass
class Planned:
    considered: int = 0
    queued: int = 0


def _allowed(settings: Settings, kind: str) -> bool:
    kinds = settings.notification_kinds
    return kinds is None or kind in kinds


async def plan_reminders(session: AsyncSession, settings: Settings, now: datetime) -> Planned:
    """Queue the reminders that are due now. The caller commits."""
    planned = Planned()
    wanted = [kind for kind in (DAILY_REMINDER, STREAK_WARNING, WEEKLY_SUMMARY) if _allowed(settings, kind)]
    if settings.notifications_mode == "off" or not wanted:
        return planned
    flags = [getattr(NotificationPreferences, kind) for kind in wanted]
    rows = await session.execute(
        select(User.id, User.email, User.timezone, User.display_name, *flags)
        .join(NotificationPreferences, NotificationPreferences.user_id == User.id)
        .where(User.timezone.is_not(None), User.email_verified_at.is_not(None), or_(*flags))
    )
    allowlist = settings.notification_allowlist
    for row in rows:
        if settings.notifications_mode == "allowlist" and not {str(row.id), row.email.lower()} & allowlist:
            continue
        planned.considered += 1
        due = {kind for kind in wanted if getattr(row, kind)}
        planned.queued += await _plan_for(session, settings, row, due, now)
    return planned


async def _queue(session: AsyncSession, row, kind: str, period: str, email: Email, before: datetime) -> int:
    # The outbox keeps a subject and a text body only, so reminders go out as text for now.
    added = await queue_email(
        session,
        kind=kind,
        to=row.email,
        subject=email.subject,
        body=email.body,
        send_before=before,
        user_id=row.id,
        dedup_key=f"{row.id}:{kind}:{period}",
    )
    return int(added)


async def _plan_for(session: AsyncSession, settings: Settings, row, due: set[str], now: datetime) -> int:
    """The reminders due now for one student (`due`: the kinds they turned on)."""
    zone = zone_for(row.timezone, settings.default_timezone)
    local = now.astimezone(zone)
    state = await snapshot(session, row.id, zone, now)
    end_of_day = datetime.combine(state.today, time(23, 59, 59), zone)
    app = settings.app_name
    app_url = app_link(settings, "home") or app
    manage = settings_link(settings)
    queued = 0

    if DAILY_REMINDER in due and not state.today_active:
        start = datetime.combine(state.today, await read_study_time(session, row.id) or DEFAULT_STUDY_TIME, zone)
        if start <= local < start + DAILY_WINDOW:
            unsubscribe = unsubscribe_url(settings, row.id, DAILY_REMINDER)
            email = emails.daily_reminder(app, app_url, manage, unsubscribe, name=row.display_name, settings=settings)
            added = await _queue(session, row, DAILY_REMINDER, state.today.isoformat(), email, start + DAILY_WINDOW)
            if added and await in_app_reminders_on(session, row.id):
                await notify(
                    session,
                    row.id,
                    kind="daily_reminder",
                    title="📚 Time to study",
                    body="Your study time is now. Ask your tutor a question to get going.",
                    link="/",
                    dedup_key=f"daily-reminder:{state.today.isoformat()}",
                )
            queued += added

    if STREAK_WARNING in due:
        streak = await streak_state(session, row.id, now)
        india = now.astimezone(LEARNING_ZONE)
        if not streak.today_active and streak.current >= 2 and STREAK_WINDOW[0] <= india.time() < STREAK_WINDOW[1]:
            unsubscribe = unsubscribe_url(settings, row.id, STREAK_WARNING)
            email = emails.streak_warning(
                app,
                streak.current,
                app_url,
                manage,
                unsubscribe,
                time_left=remaining_label(streak.day_end - now),
                name=row.display_name,
                settings=settings,
            )
            added = await _queue(session, row, STREAK_WARNING, streak.today.isoformat(), email, streak.day_end)
            if added and await in_app_reminders_on(session, row.id):
                await notify(
                    session,
                    row.id,
                    kind="streak_reminder",
                    title=f"🔥 Your {streak.current}-day streak is waiting",
                    body=f"A question today keeps it going. {remaining_label(streak.day_end - now)} left today.",
                    link="/",
                    dedup_key=f"streak-reminder:{streak.today.isoformat()}",
                )
            queued += added

    if WEEKLY_SUMMARY in due and state.last_week_active_days:
        if local.weekday() == 0 and WEEKLY_WINDOW[0] <= local.time() < WEEKLY_WINDOW[1]:
            year, week, _ = state.last_week_start.isocalendar()
            last_day = state.last_week_start + timedelta(days=6)
            unsubscribe = unsubscribe_url(settings, row.id, WEEKLY_SUMMARY)
            email = emails.weekly_summary(
                app,
                f"{state.last_week_start:%d %b} – {last_day:%d %b %Y}",
                state.last_week_minutes,
                state.last_week_questions,
                state.last_week_active_days,
                app_url,
                manage,
                unsubscribe,
                name=row.display_name,
                settings=settings,
            )
            added = await _queue(session, row, WEEKLY_SUMMARY, f"{year}-W{week:02d}", email, end_of_day)
            if added and await in_app_reminders_on(session, row.id):
                await notify(
                    session,
                    row.id,
                    kind="weekly_summary",
                    title="📊 Your week in PadhAI",
                    body=f"{state.last_week_questions} questions, {state.last_week_active_days} active days last week.",
                    link="/settings/progress",
                    dedup_key=f"weekly-summary:{year}-W{week:02d}",
                )
            queued += added
    return queued
