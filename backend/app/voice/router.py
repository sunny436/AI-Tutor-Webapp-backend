"""/v1/voice: voice mode's speech (docs/api-contract.md, "Voice").

Every route checks, itself, that voice mode is for this student: the rollout (VOICE_MODE, VOICE_QA_EMAILS) and
their tutor language (English or unset: OllaLink speaks no Hindi). Anyone else gets 404 and nothing is sent to
OllaLink. `GET /v1/voice` says the same for the web app to show its button; it decides nothing.

Bounded before OllaLink is asked: per student a minute and a day (auth_attempts), at once per student and in all
(this process), the audio's size, the speech per reply. A client that goes away cancels its OllaLink call. Audio
is never stored; logs carry sizes and times only, never what was said.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal, get_auth_service, get_principal
from app.auth.service import AuthService
from app.conversations.repository import ConversationRepository
from app.db.session import get_session
from app.errors import AppError, NotFound, PayloadTooLarge, RateLimited, ServiceUnavailable, UnsupportedMediaType
from app.learning.context import read_student_context
from app.logging import get_logger
from app.schemas import ApiModel, RequestModel
from app.voice.policy import speaks_their_language
from app.voice.provider import VoiceError, VoiceProvider

log = get_logger("app.voice")
router = APIRouter(prefix="/v1/voice", tags=["voice"])

# One utterance of up to MAX_AUDIO_SECONDS. Measured 2026-10-23 with Chromium 153's own recorder at the 24 kbit/s
# the web app asks for: WebM/Opus 2.7 KB/s, MP4/AAC 11.6 KB/s (its bitrate is not honoured), so a minute of the
# larger is 0.7 MB; with a quarter to spare, 1 MiB. The web app's proxy caps uploads at this too (`x-max-bytes`).
# Only the formats OllaLink was seen to accept (webm/opus, mp4/aac, mp4/opus, wav: all heard right, 3 of 3).
MAX_AUDIO_BYTES = 1024 * 1024
MAX_AUDIO_SECONDS = 60
AUDIO_TYPES = ("audio/webm", "audio/mp4", "audio/wav")
SPEECH_TYPES = ("audio/mpeg", "audio/ogg", "audio/aac", "audio/wav")  # wav: the fake provider only (tests, e2e)
BINARY = {"schema": {"type": "string", "format": "binary"}}
UPLOAD_BODY = {
    "requestBody": {"required": True, "content": {kind: BINARY for kind in AUDIO_TYPES}, "x-max-bytes": MAX_AUDIO_BYTES}
}
SPEECH_RESPONSE = {200: {"content": {kind: BINARY for kind in SPEECH_TYPES}}}


class VoiceOut(ApiModel):
    enabled: bool
    # Say a short pre-recorded word when the student stops, before the answer (VOICE_ACK). The web app's own audio.
    ack: bool = False
    # The server speaks a reply's first words itself (VOICE_SERVER_SPEECH): its stream's `speech` events.
    server_speech: bool = False


class TranscriptOut(ApiModel):
    text: str  # "" when nothing was heard: the student can just speak again
    seconds: float | None


class SpeechRequest(RequestModel):
    message_id: uuid.UUID  # the reply being read aloud: the student's own
    text: str = Field(min_length=1, max_length=600)
    # The audio the browser can decode, smallest first: opus (Ogg), aac (ADTS), mp3.
    format: Literal["mp3", "opus", "aac"] = "mp3"


class VoiceUnreadable(AppError):
    status_code, code, message = 422, "voice_unreadable", "We couldn't hear that clearly. Please try again."


class VoiceUnavailable(ServiceUnavailable):
    code, message = "voice_unavailable", "Voice isn't working right now. Please try again shortly."


class VoiceBusy(ServiceUnavailable):
    code, message = "voice_busy", "Voice is busy right now. Please try again in a moment."


class SpeechBudget:
    """Characters read aloud per reply, in this process: a bounded map, forgotten after an hour."""

    MAX_REPLIES = 10_000
    KEEP_S = 3600.0

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._spent: OrderedDict[uuid.UUID, tuple[int, float]] = OrderedDict()

    def spend(self, message_id: uuid.UUID, characters: int) -> bool:
        now = time.monotonic()
        while self._spent and (
            len(self._spent) > self.MAX_REPLIES or next(iter(self._spent.values()))[1] < now - self.KEEP_S
        ):
            self._spent.popitem(last=False)
        spent, since = self._spent.get(message_id, (0, now))
        if spent + characters > self.limit:
            return False
        self._spent[message_id] = (spent + characters, since)
        return True


class InFlight:
    """OllaLink calls running now, per lane, per student and in all (this process)."""

    def __init__(self) -> None:
        self.total: dict[str, int] = {"stt": 0, "tts": 0}
        self.users: dict[tuple[str, uuid.UUID], int] = {}

    @asynccontextmanager
    async def slot(self, lane: str, user_id: uuid.UUID, per_user: int, total: int):
        key = (lane, user_id)
        if self.users.get(key, 0) >= per_user:
            raise RateLimited("One moment: the last one is still being handled.")
        if self.total[lane] >= total:
            raise VoiceBusy()
        self.total[lane] += 1
        self.users[key] = self.users.get(key, 0) + 1
        try:
            yield
        finally:
            self.total[lane] -= 1
            left = self.users[key] - 1
            if left:
                self.users[key] = left
            else:
                del self.users[key]


class ClientGone(Exception):
    pass


async def _unless_gone(request: Request, work):
    """`work` (an OllaLink call), cancelled if the client goes away first: nothing is done for nobody."""
    task = asyncio.ensure_future(work)

    async def watch() -> None:
        # The body has been read, so the next message the server has for this request is its disconnect.
        while (await request.receive())["type"] != "http.disconnect":
            pass

    watcher = asyncio.ensure_future(watch())
    try:
        done, _ = await asyncio.wait({task, watcher}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        watcher.cancel()
    if task not in done:
        task.cancel()
        raise ClientGone
    try:
        return task.result()
    except VoiceError as error:
        raise (VoiceUnreadable() if error.reason == "unreadable" else VoiceUnavailable()) from None


async def available(request: Request, principal: Principal, db: AsyncSession) -> VoiceProvider | None:
    """The provider when voice mode is for this student, else None."""
    provider: VoiceProvider | None = request.app.state.voice
    if provider is None or not request.app.state.settings.voice_rollout_allows(principal.user.email):
        return None
    if not speaks_their_language(await read_student_context(db, principal.user.id)):
        return None
    return provider


async def _provider(request: Request, principal: Principal, db: AsyncSession) -> VoiceProvider:
    provider = await available(request, principal, db)
    if provider is None:
        raise NotFound()
    return provider


@router.get("", response_model=VoiceOut, summary="Whether voice mode is offered to this student")
async def get_voice(
    request: Request, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)
):
    """For the web app's button only: every voice route checks the same itself."""
    enabled = await available(request, principal, db) is not None
    settings = request.app.state.settings
    email = principal.user.email
    return VoiceOut(
        enabled=enabled,
        ack=enabled and settings.voice_feature_allows(settings.voice_ack, email),
        server_speech=enabled and settings.voice_feature_allows(settings.voice_server_speech, email),
    )


@router.post(
    "/transcriptions",
    response_model=TranscriptOut,
    openapi_extra=UPLOAD_BODY,
    summary="What the student said (one utterance, the raw audio as the body; English)",
)
async def transcribe(
    request: Request,
    seconds: float = Query(..., gt=0, le=MAX_AUDIO_SECONDS, description="The recording's length, client-measured"),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
    auth: AuthService = Depends(get_auth_service),
):
    """WebM (Opus), MP4 (AAC or Opus) or WAV, up to 1 MiB and 60 s. Nothing is stored. `text` "" = nothing heard."""
    provider = await _provider(request, principal, db)
    kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind not in AUDIO_TYPES:
        raise UnsupportedMediaType("Send the recording as WebM, MP4 or WAV audio.")
    await auth.throttle_voice(principal.user, "stt")  # commits: no transaction is held while the audio arrives
    audio = bytearray()
    async for chunk in request.stream():
        audio += chunk
        if len(audio) > MAX_AUDIO_BYTES:
            raise PayloadTooLarge("That recording is too long. Keep a question under a minute.")
    if not audio:
        raise VoiceUnreadable()
    settings = request.app.state.settings
    started = time.monotonic()
    try:
        async with request.app.state.voice_calls.slot(
            "stt",
            principal.user.id,
            settings.voice_transcriptions_in_flight_per_user,
            settings.voice_transcriptions_in_flight,
        ):
            transcript = await _unless_gone(request, provider.transcribe(bytes(audio), kind))
    except ClientGone:
        return Response(status_code=499)
    log.info(
        "voice transcribed",
        extra={
            "bytes": len(audio),
            "declared_s": seconds,
            "audio_s": transcript.seconds,
            "empty": not transcript.text,
            "latency_ms": int((time.monotonic() - started) * 1000),
        },
    )
    return TranscriptOut(text=transcript.text, seconds=transcript.seconds)


@router.post(
    "/speech",
    response_class=Response,
    responses=SPEECH_RESPONSE,
    summary="One sentence of the student's own reply, read aloud (MP3; English)",
)
async def speak(
    body: SpeechRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
    auth: AuthService = Depends(get_auth_service),
):
    """Up to 600 characters of a reply in the student's own conversation, up to VOICE_SPEECH_CHARS_PER_MESSAGE for
    one reply. Never stored or cached."""
    provider = await _provider(request, principal, db)
    message = await ConversationRepository(db).get_message(principal.user.id, body.message_id)
    if message is None or message.role != "assistant":
        raise NotFound()
    await auth.throttle_voice(principal.user, "tts")  # commits
    if not request.app.state.voice_budget.spend(body.message_id, len(body.text)):
        raise RateLimited("This reply is too long to read aloud in full; the rest is in the chat.")
    settings = request.app.state.settings
    started = time.monotonic()
    try:
        async with request.app.state.voice_calls.slot(
            "tts", principal.user.id, settings.voice_speech_in_flight_per_user, settings.voice_speech_in_flight
        ):
            audio, media = await _unless_gone(request, provider.synthesize(body.text, body.format))
    except ClientGone:
        return Response(status_code=499)
    log.info(
        "voice spoken",
        extra={
            "chars": len(body.text),
            "format": body.format,
            "bytes": len(audio),
            "latency_ms": int((time.monotonic() - started) * 1000),
        },
    )
    return Response(content=audio, media_type=media, headers={"Cache-Control": "no-store"})
