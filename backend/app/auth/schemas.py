from __future__ import annotations

import uuid
import zoneinfo
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal

from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas import ApiModel, RequestModel, check_set_reset

Password = Field(min_length=8, max_length=128)
Code = Field(pattern=r"^\d{6}$")


class SignupRequest(RequestModel):
    email: EmailStr
    password: str = Password
    display_name: str | None = Field(default=None, max_length=80)

    @field_validator("display_name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


class VerifyEmailRequest(RequestModel):
    email: EmailStr
    code: str = Code


class LoginRequest(RequestModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ResendCodeRequest(RequestModel):
    email: EmailStr
    purpose: Literal["verify_email", "reset_password"] = "verify_email"


class ForgotPasswordRequest(RequestModel):
    email: EmailStr


class ResetPasswordRequest(RequestModel):
    email: EmailStr
    code: str = Code
    new_password: str = Password


class ChangePasswordRequest(RequestModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Password


class UpdateMeRequest(RequestModel):
    display_name: str | None = Field(default=None, max_length=80)


class DeleteMeRequest(RequestModel):
    password: str = Field(min_length=1, max_length=128)


class UpdateSettingsRequest(RequestModel):
    # Top-level keys are merged; a null value removes the key.
    preferences: dict[str, Any]


class AvatarOut(ApiModel):
    # Content-addressed: the URL changes whenever the photo does, so clients may cache it
    # forever (see GET /v1/me/avatar). Relative to the API's base URL.
    url: str


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    email_verified: bool
    created_at: datetime
    # Additive fields for the Settings profile (0003_identity).
    profile_version: int = Field(description="Send it back with PATCH /v1/me/profile.")
    timezone: str | None
    avatar: AvatarOut | None
    password_changed_at: datetime | None


@lru_cache(maxsize=1)
def _timezones() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones())


def check_timezone(value: str) -> str:
    if value not in _timezones():
        raise ValueError("not an IANA time zone name")
    return value


ProfileField = Literal["displayName", "timezone"]


class ProfileSet(RequestModel):
    """Fields to set. A field absent here is left unchanged; `null` is not a value (use `reset`)."""

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value.strip() if value is not None else None

    @field_validator("timezone")
    @classmethod
    def _zone(cls, value: str | None) -> str | None:
        return check_timezone(value) if value is not None else None


class UpdateProfileRequest(RequestModel):
    """The one PATCH shape (docs/api-contract.md): `set` replaces the listed fields, `reset`
    returns fields to their defaults (both of these become empty), anything else is unchanged.
    `version` must be the profileVersion the client read; otherwise 409 version_conflict."""

    version: int = Field(ge=0)
    set: ProfileSet = Field(default_factory=ProfileSet)
    reset: list[ProfileField] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def _one_meaning_per_field(self) -> UpdateProfileRequest:
        check_set_reset(self.set, self.reset)
        return self


class SessionInfo(ApiModel):
    """A signed-in device, with safe metadata only (app/auth/devices.py)."""

    id: uuid.UUID
    current: bool
    device: str
    ip_masked: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


class SessionListOut(ApiModel):
    items: list[SessionInfo]


class EmailChangeRequest(RequestModel):
    new_email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class EmailConfirmRequest(RequestModel):
    new_email: EmailStr
    code: str = Code


class SessionOut(ApiModel):
    token: str
    expires_at: datetime


class AuthResult(ApiModel):
    user: UserOut
    session: SessionOut


class AcceptedOut(ApiModel):
    status: str = "accepted"


class SettingsOut(ApiModel):
    preferences: dict[str, Any]
    updated_at: datetime | None
