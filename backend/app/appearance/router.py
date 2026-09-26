"""GET/PATCH /v1/me/appearance: how the app looks for this user, on every device.

Versioned like every Settings resource (`{version, set, reset}`, docs/api-contract.md). Clients
apply it (theme, text size, contrast, motion, reading comfort) and may cache it locally to avoid
a flash on the next visit; this is the source of truth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator
from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal, get_principal
from app.db.models import FONT_SIZES, THEMES, AppearanceSettings
from app.db.session import get_session
from app.errors import VersionConflict
from app.schemas import ApiModel, RequestModel, check_set_reset

router = APIRouter(prefix="/v1/me", tags=["me"])

Theme = Literal[*THEMES]
FontSize = Literal[*FONT_SIZES]
AppearanceField = Literal["theme", "fontSize", "highContrast", "reduceMotion", "readingComfort", "showStreak"]

DEFAULTS = {
    "theme": "system",
    "font_size": "medium",
    "high_contrast": False,
    "reduce_motion": False,
    "reading_comfort": False,
    "show_streak": True,
}


class AppearanceSet(RequestModel):
    theme: Theme | None = None
    font_size: FontSize | None = None
    high_contrast: bool | None = None
    reduce_motion: bool | None = Field(default=None, description="Also on when the device asks for less motion.")
    reading_comfort: bool | None = Field(default=None, description="Wider line spacing in answers.")
    show_streak: bool | None = None


class UpdateAppearanceRequest(RequestModel):
    version: int = Field(ge=0)
    set: AppearanceSet = Field(default_factory=AppearanceSet)
    reset: list[AppearanceField] = Field(default_factory=list, max_length=len(DEFAULTS))

    @model_validator(mode="after")
    def _one_meaning_per_field(self) -> UpdateAppearanceRequest:
        check_set_reset(self.set, self.reset)
        return self


class AppearanceOut(ApiModel):
    version: int = Field(description="Send it back with PATCH /v1/me/appearance.")
    theme: Theme
    font_size: FontSize
    high_contrast: bool
    reduce_motion: bool
    reading_comfort: bool
    show_streak: bool
    updated_at: datetime | None


COLUMNS = {field.alias or name: name for name, field in AppearanceSet.model_fields.items()}


def appearance_out(row: AppearanceSettings | None) -> AppearanceOut:
    values = {name: getattr(row, name) for name in DEFAULTS} if row else dict(DEFAULTS)
    return AppearanceOut(version=row.version if row else 0, updated_at=row.updated_at if row else None, **values)


@router.get("/appearance", response_model=AppearanceOut)
async def get_appearance(principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)):
    return appearance_out(await db.get(AppearanceSettings, principal.user.id))


@router.patch("/appearance", response_model=AppearanceOut)
async def update_appearance(
    body: UpdateAppearanceRequest,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    user_id = principal.user.id
    changes = body.set.model_dump(include=body.set.model_fields_set)
    changes.update({COLUMNS[name]: DEFAULTS[COLUMNS[name]] for name in body.reset})
    if changes:
        await db.execute(insert(AppearanceSettings).values(user_id=user_id).on_conflict_do_nothing())
        row = await db.get(AppearanceSettings, user_id, with_for_update=True, populate_existing=True)
        if row.version != body.version:
            await db.rollback()
            current = appearance_out(await db.get(AppearanceSettings, user_id, populate_existing=True))
            raise VersionConflict(current=current.model_dump(mode="json", by_alias=True))
        await db.execute(
            update(AppearanceSettings)
            .where(AppearanceSettings.user_id == user_id)
            .values(**changes, version=AppearanceSettings.version + 1, updated_at=func.clock_timestamp())
        )
        await db.commit()
    return appearance_out(await db.get(AppearanceSettings, user_id, populate_existing=True))
