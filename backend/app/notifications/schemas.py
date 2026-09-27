from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.schemas import ApiModel, RequestModel, check_set_reset

NotificationField = Literal["dailyReminder", "streakWarning", "weeklySummary", "securityAlerts", "inAppReminders"]


class NotificationPreferencesSet(RequestModel):
    daily_reminder: bool | None = None
    streak_warning: bool | None = None
    weekly_summary: bool | None = None
    security_alerts: bool | None = Field(default=None, description="Emails about sign-ins from a new device.")
    in_app_reminders: bool | None = Field(
        default=None, description="Reminders in the app's notifications (streak, daily, weekly). On by default."
    )


class UpdateNotificationPreferencesRequest(RequestModel):
    """`{version, set, reset}`; `reset` returns a field to its default."""

    version: int = Field(ge=0)
    set: NotificationPreferencesSet = Field(default_factory=NotificationPreferencesSet)
    reset: list[NotificationField] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def _one_meaning_per_field(self) -> UpdateNotificationPreferencesRequest:
        check_set_reset(self.set, self.reset)
        return self


class NotificationPreferencesOut(ApiModel):
    version: int = Field(description="Send it back with PATCH /v1/notifications/preferences.")
    daily_reminder: bool
    streak_warning: bool
    weekly_summary: bool
    security_alerts: bool
    in_app_reminders: bool
    reminders_need_timezone: bool = Field(
        description="True while the user has no time zone: reminders are only sent once one is chosen."
    )
    delivery: Literal["active", "paused"] = Field(
        description="Whether this server currently sends notification emails to this user at all "
        "(its rollout: JOBS_ENABLED, NOTIFICATIONS_MODE). Preferences are kept either way."
    )
    updated_at: datetime | None


class NotificationOut(ApiModel):
    id: uuid.UUID
    kind: str
    title: str = Field(description="Plain text.")
    body: str = Field(description="Plain text.")
    link: str | None = Field(description="A path in this app, when there is somewhere to go.")
    created_at: datetime
    read_at: datetime | None


class NotificationsOut(ApiModel):
    items: list[NotificationOut] = Field(description="Newest first; never more than 30.")
    unread_count: int


class MarkReadRequest(RequestModel):
    ids: list[uuid.UUID] | None = Field(
        default=None, max_length=30, description="The notifications to mark read; omitted: all of yours."
    )


class UnsubscribeRequest(RequestModel):
    token: str = Field(min_length=10, max_length=300)


class UnsubscribeOut(ApiModel):
    kind: str
    unsubscribed: bool = True
