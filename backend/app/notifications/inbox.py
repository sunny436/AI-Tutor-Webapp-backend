"""The in-app notifications behind the header's bell.

- **One place writes them:** `notify`, an insert that does nothing when the same `dedup_key`
  exists for the user. That makes each notification happen once: a streak milestone once
  ever, a reminder once a day, an alert once per event, however often the caller runs.
- **Plain text only.** Titles and bodies are shown as text (never HTML), so nothing a student
  or an event carries can become markup.
- **Every existing email event also appears here** (security alerts, reminders), and streak
  milestones only here. Emails keep their own switches (notification_preferences); in-app
  reminders follow `in_app_reminders`, security alerts and milestones are always shown.
- **The streak reminder needs no scheduler:** it is created when the student's list is read
  (`ensure_streak_reminder`), in the evening of a day with no learning yet.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationPreferences, UserNotification

LIST_MAX = 30
READ_KEPT = timedelta(days=90)
REMINDER_FROM = time(18, 0)  # India time: evenings only


@dataclass(frozen=True)
class Inbox:
    items: list[UserNotification]
    unread: int


async def notify(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    kind: str,
    title: str,
    body: str,
    dedup_key: str,
    link: str | None = None,
) -> bool:
    """Add one notification, unless one with this `dedup_key` exists. Part of the caller's
    transaction. True when it was added."""
    statement = (
        insert(UserNotification)
        .values(user_id=user_id, kind=kind, title=title[:120], body=body[:400], link=link, dedup_key=dedup_key)
        .on_conflict_do_nothing(index_elements=[UserNotification.user_id, UserNotification.dedup_key])
        .returning(UserNotification.id)
    )
    return (await session.execute(statement)).first() is not None


async def in_app_reminders_on(session: AsyncSession, user_id: uuid.UUID) -> bool:
    preferences = await session.get(NotificationPreferences, user_id)
    return preferences is None or preferences.in_app_reminders


async def list_for(session: AsyncSession, user_id: uuid.UUID, limit: int = LIST_MAX) -> Inbox:
    """The newest notifications not cleared (never more than LIST_MAX), and how many are unread:
    all of them, not only the ones listed."""
    limit = max(1, min(limit, LIST_MAX))
    shown = (UserNotification.user_id == user_id, UserNotification.cleared_at.is_(None))
    items = (
        await session.scalars(
            select(UserNotification)
            .where(*shown)
            .order_by(UserNotification.created_at.desc(), UserNotification.id.desc())
            .limit(limit)
        )
    ).all()
    unread = await session.scalar(
        select(func.count()).select_from(UserNotification).where(*shown, UserNotification.read_at.is_(None))
    )
    return Inbox(items=list(items), unread=unread or 0)


async def mark_read(session: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID] | None) -> int:
    """Mark the student's own notifications read: the ones listed, or all of them (also those
    beyond the LIST_MAX shown). Ids of anyone else's notifications match nothing. Returns how
    many changed; marking again changes nothing."""
    statement = update(UserNotification).where(UserNotification.user_id == user_id, UserNotification.read_at.is_(None))
    if ids is not None:
        statement = statement.where(UserNotification.id.in_(ids))
    return (await session.execute(statement.values(read_at=func.clock_timestamp()))).rowcount


async def clear_all(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Clear all: every notification of the student's leaves the bell and counts as read. Rows
    stay until `purge_read` deletes them, so a cleared one keeps its dedup_key (today's reminder is
    not made again) and anything new still arrives. Returns how many changed; clearing again, or
    alongside "Read all", changes nothing more (each touches only rows still not cleared / unread)."""
    result = await session.execute(
        update(UserNotification)
        .where(UserNotification.user_id == user_id, UserNotification.cleared_at.is_(None))
        .values(
            cleared_at=func.clock_timestamp(),
            read_at=func.coalesce(UserNotification.read_at, func.clock_timestamp()),
        )
    )
    return result.rowcount


async def purge_read(session: AsyncSession, now: datetime) -> int:
    """Retention (the jobs worker): notifications read more than 90 days ago are deleted."""
    result = await session.execute(delete(UserNotification).where(UserNotification.read_at < now - READ_KEPT))
    return result.rowcount


async def ensure_streak_reminder(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> bool:
    """In the evening (India time) of a day with no learning yet, remind a student who has a
    streak going, or has learnt before, once that day. Nothing when they turned in-app
    reminders off, or already learnt today."""
    from app.progress.learning import LEARNING_ZONE, remaining_label, streak_state

    local = now.astimezone(LEARNING_ZONE)
    if local.time() < REMINDER_FROM or not await in_app_reminders_on(session, user_id):
        return False
    state = await streak_state(session, user_id, now)
    if state.today_active or (state.current == 0 and state.longest == 0):
        return False
    left = remaining_label(state.day_end - now)
    if state.current >= 1:
        title = f"🔥 Your {state.current}-day streak is waiting"
        body = f"A question today keeps it going. You have {left} left today."
    else:
        title = "🔥 Start a new streak today"
        body = f"Ask your tutor a question to begin. You have {left} left today."
    return await notify(
        session,
        user_id,
        kind="streak_reminder",
        title=title,
        body=body,
        link="/",
        dedup_key=f"streak-reminder:{state.today.isoformat()}",
    )
