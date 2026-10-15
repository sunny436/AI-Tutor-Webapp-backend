from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal, get_principal
from app.db.session import get_session
from app.errors import RateLimited
from app.study.schemas import (
    ChaptersOut,
    StudyBeatIn,
    StudyContextChangeIn,
    StudyStartIn,
    StudyStateOut,
    StudySummaryOut,
    StudyTransitionIn,
)
from app.study.service import MAX_DAYS, StudyService

router = APIRouter(prefix="/v1/study", tags=["study"])


def get_study_service(request: Request, db: AsyncSession = Depends(get_session)) -> StudyService:
    settings = request.app.state.settings
    return StudyService(db, settings.default_timezone, request.app.state.study_chapters)


def _state(request: Request, state: dict) -> StudyStateOut:
    settings = request.app.state.settings
    return StudyStateOut.model_validate(
        {
            **state,
            "idle": {
                "reading_seconds": settings.study_idle_reading_s,
                "solving_seconds": settings.study_idle_solving_s,
            },
        }
    )


def _limit(request: Request, limiter: str, principal: Principal) -> None:
    if not getattr(request.app.state, limiter).allow(str(principal.user.id)):
        raise RateLimited()


@router.get("/session", response_model=StudyStateOut)
async def get_study_session(
    request: Request, principal: Principal = Depends(get_principal), study: StudyService = Depends(get_study_service)
):
    """The open study session (if any) and the latest one that ended in the last day, as of now: a
    session that ended on its own (no study activity for 15 minutes, paused for 60, or 8 hours) is
    shown as ended. Only reads."""
    return _state(request, await study.state(principal.user))


@router.post("/session", response_model=StudyStateOut)
async def start_study_session(
    body: StudyStartIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    study: StudyService = Depends(get_study_service),
):
    """Start studying, or join the session already open on another tab or device (as it is)."""
    _limit(request, "study_action_limiter", principal)
    state = await study.start(principal.user, body.client_id, body.subject, body.chapter_id, body.activity)
    return _state(request, state)


@router.patch("/session/{session_id}", response_model=StudyStateOut)
async def change_study_context(
    session_id: uuid.UUID,
    body: StudyContextChangeIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    study: StudyService = Depends(get_study_service),
):
    """Change the subject, chapter or activity. 409 study_state_changed if the session changed since
    `expectedSegmentId` (unless it already has this context); 409 study_session_ended once ended."""
    _limit(request, "study_action_limiter", principal)
    state = await study.change_context(
        principal.user,
        session_id,
        body.client_id,
        body.expected_segment_id,
        body.subject,
        body.chapter_id,
        body.activity,
    )
    return _state(request, state)


@router.post("/session/{session_id}/pause", response_model=StudyStateOut)
async def pause_study_session(
    session_id: uuid.UUID,
    body: StudyTransitionIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    study: StudyService = Depends(get_study_service),
):
    """Pause (already paused: nothing changes). Paused time is never active time."""
    _limit(request, "study_action_limiter", principal)
    state = await study.pause(principal.user, session_id, body.client_id, body.expected_segment_id)
    return _state(request, state)


@router.post("/session/{session_id}/resume", response_model=StudyStateOut)
async def resume_study_session(
    session_id: uuid.UUID,
    body: StudyTransitionIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    study: StudyService = Depends(get_study_service),
):
    """Resume (already studying: nothing changes)."""
    _limit(request, "study_action_limiter", principal)
    state = await study.resume(principal.user, session_id, body.client_id, body.expected_segment_id)
    return _state(request, state)


@router.post("/session/{session_id}/end", response_model=StudyStateOut)
async def end_study_session(
    session_id: uuid.UUID,
    body: StudyTransitionIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    study: StudyService = Depends(get_study_service),
):
    """End the session (already ended: nothing changes)."""
    _limit(request, "study_action_limiter", principal)
    state = await study.end(principal.user, session_id, body.client_id, body.expected_segment_id)
    return _state(request, state)


@router.post("/beat", response_model=StudyStateOut)
async def study_beat(
    body: StudyBeatIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    study: StudyService = Depends(get_study_service),
):
    """One observation from one client, every 30 s and at every change. Credits active time only
    between two of this client's observations at most 75 s apart, both active, inside studying
    time; never twice for the same moment, however many tabs or devices report it."""
    _limit(request, "study_beat_limiter", principal)
    state = await study.beat(
        principal.user, body.beat_id, body.client_id, body.was_active, body.now_active, body.study_view, body.visible
    )
    return _state(request, state)


@router.get("/summary", response_model=StudySummaryOut)
async def get_study_summary(
    days: int = Query(default=7, ge=1, le=MAX_DAYS, description="The last `days` days, ending today."),
    principal: Principal = Depends(get_principal),
    study: StudyService = Depends(get_study_service),
):
    """Estimated active, idle and paused study time and app time per day, by subject, chapter and
    activity, and the sessions in the range. Days are in the student's time zone; days before
    anything was recorded are left out rather than shown as zero."""
    return StudySummaryOut.model_validate(await study.summary(principal.user, days))


@router.get("/chapters", response_model=ChaptersOut)
async def get_study_chapters(
    subject: str = Query(max_length=40, description="A subject code."),
    principal: Principal = Depends(get_principal),
    study: StudyService = Depends(get_study_service),
):
    """NCERT chapters of this subject for the student's class (Academic Profile), for choosing what
    a session is about. No list (`available: false`) is a normal state: studying needs no chapter."""
    reason, chapters = await study.chapter_list(principal.user, subject)
    return ChaptersOut.model_validate({"available": reason is None, "reason": reason, "chapters": chapters})
