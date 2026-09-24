from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import EmailStr, Field, field_validator

from app.schemas import ApiModel, RequestModel

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


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    email_verified: bool
    created_at: datetime


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
