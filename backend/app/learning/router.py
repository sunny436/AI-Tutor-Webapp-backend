from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal, get_principal, get_settings_dep
from app.db.models import PREFERENCE_CHOICES, LearnerProfile, LearnerSubject, LearningPreferences
from app.db.session import get_session
from app.errors import RateLimited, VersionConflict
from app.learning import catalog
from app.learning.context import SubjectChoice
from app.learning.schemas import (
    AcademicCatalogOut,
    LearnerProfileOut,
    LearnerProfileSet,
    LearningPreferencesOut,
    LearningPreferencesSet,
    ReplaceSubjectsRequest,
    SubjectIn,
    SubjectOut,
    SubjectsOut,
    TutorPreviewOut,
    TutorPreviewRequest,
    UpdateLearnerProfileRequest,
    UpdateLearningPreferencesRequest,
)
from app.learning.service import LearningService
from app.learning.tutor import MAX_TUTOR_BLOCK_CHARS

# The one reach into another domain: the preview shows the tutor's "Learning so far" line too.
from app.progress.learning import now, tutor_progress
from app.settings import Settings

router = APIRouter(prefix="/v1", tags=["learning"])

CATALOG_BODY = AcademicCatalogOut.model_validate(catalog.as_json()).model_dump(mode="json", by_alias=True)
CATALOG_HEADERS = {"ETag": catalog.ETAG, "Cache-Control": "public, max-age=3600, must-revalidate"}


def get_learning_service(db: AsyncSession = Depends(get_session)) -> LearningService:
    return LearningService(db)


def _columns(model: type[LearnerProfileSet] | type[LearningPreferencesSet]) -> dict[str, str]:
    """camelCase field name -> column name."""
    return {field.alias or name: name for name, field in model.model_fields.items()}


PROFILE_COLUMNS = _columns(LearnerProfileSet)
PREFERENCE_COLUMNS = _columns(LearningPreferencesSet)


def profile_out(row: LearnerProfile | None) -> LearnerProfileOut:
    if row is None:
        return LearnerProfileOut.model_validate(
            {name: None for name in LearnerProfileOut.model_fields}
            | {
                "version": 0,
                "weak_topics": [],
            }
        )
    return LearnerProfileOut(
        version=row.version,
        grade=row.grade,
        board=row.board,
        board_state=row.board_state,
        medium=row.medium,
        academic_year=row.academic_year,
        main_goal=row.main_goal,
        target_exam=row.target_exam,
        target_score_percent=row.target_score_percent,
        weak_topics=list(row.weak_topics),
        daily_active_minutes_goal=row.daily_active_minutes_goal,
        weekly_active_minutes_goal=row.weekly_active_minutes_goal,
        preferred_study_time=row.preferred_study_time.strftime("%H:%M") if row.preferred_study_time else None,
        short_term_goal=row.short_term_goal,
        long_term_goal=row.long_term_goal,
        exam_date=row.exam_date,
        updated_at=row.updated_at,
    )


def subjects_out(version: int, rows: list[LearnerSubject]) -> SubjectsOut:
    return SubjectsOut(
        version=version,
        items=[
            SubjectOut(code=row.subject_code, is_priority=row.is_priority, needs_improvement=row.needs_improvement)
            for row in rows
        ],
    )


def preferences_out(row: LearningPreferences | None) -> LearningPreferencesOut:
    values = {name: getattr(row, name) if row else "auto" for name in PREFERENCE_CHOICES}
    return LearningPreferencesOut(
        version=row.version if row else 0, updated_at=row.updated_at if row else None, **values
    )


def _conflict(current) -> VersionConflict:
    return VersionConflict(current=current.model_dump(mode="json", by_alias=True))


def _choices(items: list[SubjectIn]) -> list[SubjectChoice]:
    return [SubjectChoice(item.code, item.is_priority, item.needs_improvement) for item in items]


# ----------------------------------------------------------------------- catalog
@router.get("/catalog/academic", response_model=AcademicCatalogOut, tags=["catalog"])
async def academic_catalog(request: Request):
    """The values a learner profile may use. Public and the same for everyone: cache it by its
    ETag (`If-None-Match` answers 304). Codes are permanent; `deprecated` ones are shown but can
    no longer be chosen anew."""
    sent = {tag.strip() for tag in request.headers.get("if-none-match", "").split(",")}
    if catalog.ETAG in sent or "*" in sent:
        return Response(status_code=304, headers=CATALOG_HEADERS)
    return JSONResponse(content=CATALOG_BODY, headers=CATALOG_HEADERS)


# ----------------------------------------------------------------------- profile
@router.get("/learning/profile", response_model=LearnerProfileOut)
async def get_learner_profile(
    principal: Principal = Depends(get_principal), learning: LearningService = Depends(get_learning_service)
):
    user_id = principal.user.id
    return profile_out(await learning.get_profile(user_id))


@router.patch("/learning/profile", response_model=LearnerProfileOut)
async def update_learner_profile(
    body: UpdateLearnerProfileRequest,
    principal: Principal = Depends(get_principal),
    learning: LearningService = Depends(get_learning_service),
):
    """Versioned edit: `{version, set, reset}` (docs/api-contract.md). Catalog codes must exist;
    a deprecated one may only be kept. `boardState` needs board `state`."""
    user_id = principal.user.id
    changes = body.set.model_dump(include=body.set.model_fields_set)
    reset = [PROFILE_COLUMNS[name] for name in body.reset]
    try:
        row = await learning.update_profile(user_id, body.version, changes, reset)
    except VersionConflict:
        raise _conflict(profile_out(await learning.get_profile(user_id))) from None
    return profile_out(row)


# ---------------------------------------------------------------------- subjects
@router.get("/learning/subjects", response_model=SubjectsOut)
async def get_subjects(
    principal: Principal = Depends(get_principal), learning: LearningService = Depends(get_learning_service)
):
    user_id = principal.user.id
    return subjects_out(*await learning.get_subjects(user_id))


@router.put("/learning/subjects", response_model=SubjectsOut)
async def replace_subjects(
    body: ReplaceSubjectsRequest,
    principal: Principal = Depends(get_principal),
    learning: LearningService = Depends(get_learning_service),
):
    """Replaces the whole list; its order is the order to show. Versioned like a PATCH."""
    user_id = principal.user.id
    try:
        version, rows = await learning.replace_subjects(user_id, body.version, _choices(body.items))
    except VersionConflict:
        raise _conflict(subjects_out(*await learning.get_subjects(user_id))) from None
    return subjects_out(version, rows)


# ------------------------------------------------------------------- preferences
@router.get("/learning/preferences", response_model=LearningPreferencesOut)
async def get_learning_preferences(
    principal: Principal = Depends(get_principal), learning: LearningService = Depends(get_learning_service)
):
    user_id = principal.user.id
    return preferences_out(await learning.get_preferences(user_id))


@router.patch("/learning/preferences", response_model=LearningPreferencesOut)
async def update_learning_preferences(
    body: UpdateLearningPreferencesRequest,
    principal: Principal = Depends(get_principal),
    learning: LearningService = Depends(get_learning_service),
):
    """Versioned edit: `{version, set, reset}`; `reset` returns a preference to `auto`."""
    user_id = principal.user.id
    changes = body.set.model_dump(include=body.set.model_fields_set)
    reset = [PREFERENCE_COLUMNS[name] for name in body.reset]
    try:
        row = await learning.update_preferences(user_id, body.version, changes, reset)
    except VersionConflict:
        raise _conflict(preferences_out(await learning.get_preferences(user_id))) from None
    return preferences_out(row)


# ------------------------------------------------------------------ tutor preview
@router.post("/learning/tutor-preview", response_model=TutorPreviewOut)
async def tutor_preview(
    body: TutorPreviewRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    learning: LearningService = Depends(get_learning_service),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
):
    """What the tutor would be told with these (unsaved) edits: the same function the chat
    uses, with the same "Learning so far", so the preview is exactly what the next message is
    told. Nothing is saved."""
    user_id = principal.user.id
    if not request.app.state.tutor_preview_limiter.allow(str(user_id)):
        raise RateLimited()
    progress = await tutor_progress(db, user_id, principal.user.timezone, settings.default_timezone, now())
    instructions = await learning.preview_instructions(
        user_id,
        body.profile.model_dump(include=body.profile.model_fields_set) if body.profile else None,
        _choices(body.subjects) if body.subjects is not None else None,
        body.preferences.model_dump(include=body.preferences.model_fields_set) if body.preferences else None,
        progress,
    )
    return TutorPreviewOut(instructions=instructions, max_chars=MAX_TUTOR_BLOCK_CHARS)
