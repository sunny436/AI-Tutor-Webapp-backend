from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal, client_info, get_principal
from app.db.models import NotificationPreferences, User
from app.db.session import get_session
from app.errors import AppError, RateLimited, VersionConflict
from app.notifications.schemas import (
    NotificationPreferencesOut,
    NotificationPreferencesSet,
    UnsubscribeOut,
    UnsubscribeRequest,
    UpdateNotificationPreferencesRequest,
)
from app.notifications.tokens import PREFERENCE_OF, read_token

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])

COLUMNS = {field.alias or name: name for name, field in NotificationPreferencesSet.model_fields.items()}
DEFAULTS = {"daily_reminder": False, "streak_warning": False, "weekly_summary": False, "security_alerts": True}


class InvalidToken(AppError):
    status_code, code, message = 400, "invalid_token", "This link is not valid."


def preferences_out(row: NotificationPreferences | None, user: User) -> NotificationPreferencesOut:
    values = {name: getattr(row, name) for name in DEFAULTS} if row else dict(DEFAULTS)
    return NotificationPreferencesOut(
        version=row.version if row else 0,
        updated_at=row.updated_at if row else None,
        reminders_need_timezone=user.timezone is None,
        **values,
    )


async def _locked(db: AsyncSession, user_id: uuid.UUID) -> NotificationPreferences:
    await db.execute(insert(NotificationPreferences).values(user_id=user_id).on_conflict_do_nothing())
    return await db.get(NotificationPreferences, user_id, with_for_update=True, populate_existing=True)


@router.get("/preferences", response_model=NotificationPreferencesOut)
async def get_notification_preferences(
    principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)
):
    return preferences_out(await db.get(NotificationPreferences, principal.user.id), principal.user)


@router.patch("/preferences", response_model=NotificationPreferencesOut)
async def update_notification_preferences(
    body: UpdateNotificationPreferencesRequest,
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
                current=preferences_out(current, await db.get(User, user_id)).model_dump(mode="json", by_alias=True)
            )
        await db.execute(
            update(NotificationPreferences)
            .where(NotificationPreferences.user_id == user_id)
            .values(**changes, version=NotificationPreferences.version + 1, updated_at=func.clock_timestamp())
        )
        await db.commit()
    row = await db.get(NotificationPreferences, user_id, populate_existing=True)
    return preferences_out(row, await db.get(User, user_id))


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
