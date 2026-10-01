from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal, client_info, get_principal
from app.db.models import NotificationPreferences, User
from app.db.session import get_session
from app.errors import AppError, RateLimited, VersionConflict
from app.logging import get_logger
from app.notifications import inbox
from app.notifications.schemas import (
    MarkReadRequest,
    NotificationOut,
    NotificationPreferencesOut,
    NotificationPreferencesSet,
    NotificationsOut,
    UnsubscribeOut,
    UnsubscribeRequest,
    UpdateNotificationPreferencesRequest,
)
from app.notifications.tokens import PREFERENCE_OF, read_token
from app.progress.learning import now
from app.settings import Settings

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])
log = get_logger("app.notifications")

COLUMNS = {field.alias or name: name for name, field in NotificationPreferencesSet.model_fields.items()}
DEFAULTS = {
    "daily_reminder": False,
    "streak_warning": False,
    "weekly_summary": False,
    "security_alerts": True,
    "in_app_reminders": True,
}


class InvalidToken(AppError):
    status_code, code, message = 400, "invalid_token", "This link is not valid."


def delivery_for(settings: Settings, user: User) -> str:
    """Whether emails reach this user now: only while the worker runs and its rollout includes
    them. Read from the settings this API process started with (restart aichat-api after
    changing the rollout for this to show it)."""
    if not settings.jobs_enabled or settings.jobs_problems() or settings.notifications_mode in ("off", "dry_run"):
        return "paused"
    if settings.notifications_mode == "allowlist":
        return "active" if {str(user.id), user.email.lower()} & settings.notification_allowlist else "paused"
    return "active"


def preferences_out(row: NotificationPreferences | None, user: User, settings: Settings) -> NotificationPreferencesOut:
    values = {name: getattr(row, name) for name in DEFAULTS} if row else dict(DEFAULTS)
    return NotificationPreferencesOut(
        version=row.version if row else 0,
        updated_at=row.updated_at if row else None,
        reminders_need_timezone=user.timezone is None,
        delivery=delivery_for(settings, user),
        **values,
    )


async def _locked(db: AsyncSession, user_id: uuid.UUID) -> NotificationPreferences:
    await db.execute(insert(NotificationPreferences).values(user_id=user_id).on_conflict_do_nothing())
    return await db.get(NotificationPreferences, user_id, with_for_update=True, populate_existing=True)


@router.get("", response_model=NotificationsOut)
async def list_notifications(
    limit: int = Query(default=inbox.LIST_MAX, ge=1, le=inbox.LIST_MAX, description="At most 30."),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    """The student's notifications for the bell, newest first, and how many are unread. In the
    evening of a day without learning, this is also when the streak reminder is added."""
    user_id = principal.user.id
    if await inbox.ensure_streak_reminder(db, user_id, now()):
        await db.commit()
    result = await inbox.list_for(db, user_id, limit)
    return NotificationsOut(
        items=[
            NotificationOut(
                id=item.id,
                kind=item.kind,
                title=item.title,
                body=item.body,
                link=item.link,
                created_at=item.created_at,
                read_at=item.read_at,
            )
            for item in result.items
        ],
        unread_count=result.unread,
    )


@router.post("/read", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def mark_notifications_read(
    body: MarkReadRequest, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)
):
    """Mark notifications read: the ones listed, or (no `ids`) every one of the student's, also
    those beyond the 30 the list shows. Only their own. Opening the bell reads nothing."""
    rows = await inbox.mark_read(db, principal.user.id, body.ids)
    await db.commit()
    log.info("notifications read", extra={"rows": rows, "all": body.ids is None})


@router.post("/clear", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def clear_notifications(principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)):
    """Clear all: every notification of the student's leaves the list and counts as read; new
    ones still arrive. Clearing again changes nothing."""
    rows = await inbox.clear_all(db, principal.user.id)
    await db.commit()
    log.info("notifications cleared", extra={"rows": rows})


@router.get("/preferences", response_model=NotificationPreferencesOut)
async def get_notification_preferences(
    request: Request, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)
):
    row = await db.get(NotificationPreferences, principal.user.id)
    return preferences_out(row, principal.user, request.app.state.settings)


@router.patch("/preferences", response_model=NotificationPreferencesOut)
async def update_notification_preferences(
    body: UpdateNotificationPreferencesRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    """Versioned edit: `{version, set, reset}` (docs/api-contract.md). Emails are sent only while
    the server's rollout allows them (NOTIFICATIONS_MODE); reminders also need a time zone."""
    user = principal.user
    user_id = user.id
    changes = body.set.model_dump(include=body.set.model_fields_set)
    changes.update({COLUMNS[name]: DEFAULTS[COLUMNS[name]] for name in body.reset})
    if changes:
        row = await _locked(db, user_id)
        if row.version != body.version:
            await db.rollback()
            current = await db.get(NotificationPreferences, user_id, populate_existing=True)
            raise VersionConflict(
                current=preferences_out(current, await db.get(User, user_id), request.app.state.settings).model_dump(
                    mode="json", by_alias=True
                )
            )
        await db.execute(
            update(NotificationPreferences)
            .where(NotificationPreferences.user_id == user_id)
            .values(**changes, version=NotificationPreferences.version + 1, updated_at=func.clock_timestamp())
        )
        await db.commit()
    row = await db.get(NotificationPreferences, user_id, populate_existing=True)
    return preferences_out(row, await db.get(User, user_id), request.app.state.settings)


@router.post("/unsubscribe", response_model=UnsubscribeOut)
async def unsubscribe(body: UnsubscribeRequest, request: Request, db: AsyncSession = Depends(get_session)):
    """The link in a reminder or alert email. No sign-in: the signed token names the student and
    the kind of email, and nothing else can be changed with it. Using it again changes nothing."""
    if not request.app.state.unsubscribe_limiter.allow(client_info(request).ip or "unknown"):
        raise RateLimited()
    parsed = read_token(request.app.state.settings, body.token)
    if parsed is None:
        raise InvalidToken()
    user_id, kind = parsed
    if await db.get(User, user_id) is None:  # the account was deleted: nothing left to stop
        return UnsubscribeOut(kind=kind)
    column = PREFERENCE_OF[kind]
    row = await _locked(db, user_id)
    if getattr(row, column):
        await db.execute(
            update(NotificationPreferences)
            .where(NotificationPreferences.user_id == user_id)
            .values(
                {column: False, "version": NotificationPreferences.version + 1, "updated_at": func.clock_timestamp()}
            )
        )
    await db.commit()
    return UnsubscribeOut(kind=kind)
