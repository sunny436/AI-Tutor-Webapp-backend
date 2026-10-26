"""OllaLink speech for voice mode, English only.

Speech-to-text: `POST {OLLALINK_STT_URL}/v1/audio/transcriptions` (the fast file lane, gpu-transcribe): multipart
`file` + `language=en`, one whole utterance per request. Its realtime lane is a WebSocket that needs the key in a
header, which the web app's HTTP proxy cannot carry, so nothing here streams. Text-to-speech: `POST
{OLLALINK_TTS_URL}/v1/audio/speech`, JSON `input`, `language`, `voice`, `response_format` (mp3, opus or aac:
what the browser decodes), one sentence per request (no streaming: its `X-Generate-Seconds` header is sent with
the whole audio). Both with the header `X-NH-GPU-Key`: the key is the credential, never logged.

Measured from the production host on 2026-10-23: a 4.6 s question transcribed in 0.90 s (p50 of 3), a sentence of a
reply spoken in 0.70 s (p50 of 5); empty or unreadable audio is a fast 400 `bad_audio`; speech output has only
de/en/es/fr/pt (`language=hi` is a 400), so voice mode is English only.

Retried once, and only when nothing was done: a connection that could not be made, or the transcription lane's
503, which its documentation says to retry ("you get 503 and should retry"). A timeout, a cut connection or any
other answer is never retried: the work may have been done, and billed.
"""

from __future__ import annotations

import asyncio
import io
import math
import struct
import time
import wave
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.logging import get_logger

log = get_logger("app.voice")

RETRY_DELAY_S = 0.3
# Connections to OllaLink are kept a minute (httpx's default is 5 s): a voice conversation's next request usually
# comes 10-30 s after the last, and a new TLS connection costs about 0.3 s (two 141 ms round trips) before every
# transcription and every reply's first sentence. A connection OllaLink closed meanwhile is never reused.
KEEPALIVE_S = 60.0
# Largest speech answer accepted from the provider: a 600-character sentence is about 40 s of mp3 at the
# measured 16 KB/s, so 2 MB is ample; anything bigger is refused, never passed on.
MAX_SPEECH_BYTES = 2 * 1024 * 1024
# What the browser can decode, smallest first (features/voice decides by decoding a real clip): Ogg Opus and
# ADTS AAC are half the bytes of MP3 for the same speech (19 KB vs 41 KB for a 33-character phrase, measured
# 2026-10-26), which arrives from OllaLink about 160 ms sooner (141 ms round trips) and sooner to every phone.
SPEECH_FORMATS = {"mp3": "audio/mpeg", "opus": "audio/ogg", "aac": "audio/aac"}


@dataclass(frozen=True)
class Transcript:
    text: str
    seconds: float | None


class VoiceError(Exception):
    """`unreadable`: the audio could not be read (the student can try again); `unavailable`: the provider failed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class VoiceProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes, content_type: str) -> Transcript: ...

    async def synthesize(self, text: str, fmt: str = "mp3") -> tuple[bytes, str]: ...

    async def aclose(self) -> None: ...


class OllalinkVoice:
    name = "ollalink"

    def __init__(
        self,
        stt_url: str,
        tts_url: str,
        api_key: str,
        voice: str,
        *,
        stt_timeout_s: float = 25.0,
        tts_timeout_s: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.stt_url = f"{stt_url.rstrip('/')}/v1/audio/transcriptions"
        self.tts_url = f"{tts_url.rstrip('/')}/v1/audio/speech"
        self.voice = voice
        self.stt_timeout_s = stt_timeout_s
        self.tts_timeout_s = tts_timeout_s
        self._client = httpx.AsyncClient(
            headers={"X-NH-GPU-Key": api_key},
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8, keepalive_expiry=KEEPALIVE_S),
            transport=transport,
        )

    async def transcribe(self, audio: bytes, content_type: str) -> Transcript:
        name = "utterance." + {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/wav": "wav"}.get(
            content_type, "bin"
        )
        response = await self._send(
            "stt",
            lambda: self._client.post(
                self.stt_url,
                files={"file": (name, audio, content_type)},
                data={"language": "en"},
                timeout=httpx.Timeout(self.stt_timeout_s - 5, connect=3.0),
            ),
            self.stt_timeout_s,
            retry_unavailable=True,
        )
        if response.status_code == 400:
            raise VoiceError("unreadable")
        if response.status_code != 200:
            raise VoiceError("unavailable")
        try:
            body = response.json()
            text = body.get("text")
            seconds = body.get("duration")
        except (ValueError, AttributeError):
            raise VoiceError("unavailable") from None
        if not isinstance(text, str):
            raise VoiceError("unavailable")
        return Transcript(" ".join(text.split()), float(seconds) if isinstance(seconds, (int, float)) else None)

    async def synthesize(self, text: str, fmt: str = "mp3") -> tuple[bytes, str]:
        expected = SPEECH_FORMATS[fmt]
        response = await self._send(
            "tts",
            lambda: self._client.post(
                self.tts_url,
                json={"input": text, "language": "en", "voice": self.voice, "response_format": fmt},
                timeout=httpx.Timeout(self.tts_timeout_s - 3, connect=3.0),
            ),
            self.tts_timeout_s,
            retry_unavailable=False,
        )
        media = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if response.status_code != 200 or media != expected or not response.content:
            raise VoiceError("unavailable")
        if len(response.content) > MAX_SPEECH_BYTES:
            raise VoiceError("unavailable")
        return response.content, expected

    async def _send(self, lane: str, request, deadline_s: float, *, retry_unavailable: bool) -> httpx.Response:
        started = time.monotonic()
        try:
            async with asyncio.timeout(deadline_s):
                for attempt in (1, 2):
                    try:
                        response = await request()
                    except (httpx.ConnectError, httpx.ConnectTimeout) as error:  # never sent: nothing was done
                        if attempt == 2:
                            self._log(lane, started, None, type(error).__name__)
                            raise VoiceError("unavailable") from None
                        await asyncio.sleep(RETRY_DELAY_S)
                        continue
                    except httpx.HTTPError as error:  # a timeout or a cut connection: maybe done, never retried
                        self._log(lane, started, None, type(error).__name__)
                        raise VoiceError("unavailable") from None
                    if response.status_code == 503 and retry_unavailable and attempt == 1:
                        await asyncio.sleep(RETRY_DELAY_S)
                        continue
                    self._log(lane, started, response.status_code, None, attempt)
                    return response
        except TimeoutError:
            self._log(lane, started, None, "deadline")
            raise VoiceError("unavailable") from None
        raise VoiceError("unavailable")  # pragma: no cover - the loop always returns or raises

    @staticmethod
    def _log(lane: str, started: float, status: int | None, error: str | None, attempts: int = 1) -> None:
        # Metadata only: never the audio, the transcript or the text.
        log.info(
            "voice provider",
            extra={
                "lane": lane,
                "status": status,
                "error_type": error,
                "attempts": attempts,
                "latency_ms": int((time.monotonic() - started) * 1000),
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def build_voice(settings) -> VoiceProvider | None:
    """OllaLink's speech, or None: VOICE_MODE off, or no key. The fake is for tests and the e2e stack; production
    refuses it (Settings.validate_for_env), and so does this."""
    if settings.voice_mode == "off":
        return None
    if settings.voice_provider == "fake":
        if settings.is_production:
            raise RuntimeError("VOICE_PROVIDER=fake is not allowed in production")
        return FakeVoice()
    key = settings.ollalink_api_key.get_secret_value()
    if not key:
        return None
    return OllalinkVoice(settings.ollalink_stt_url, settings.ollalink_tts_url, key, settings.voice_tts_voice)


def tone_wav(seconds: float, rate: int = 16_000) -> bytes:
    """A quiet 440 Hz tone as 16-bit mono WAV: the fake provider's speech."""
    frames = int(seconds * rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(
            b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * n / rate))) for n in range(frames))
        )
    return buffer.getvalue()


class FakeVoice:
    """Deterministic speech for tests and the e2e stack (VOICE_PROVIDER=fake; refused in production): every
    recording is heard as `transcript`, and every sentence is spoken as a tone of 90 ms per character (0.3-3 s),
    long enough for the e2e tests to interrupt it."""

    name = "fake"

    def __init__(self, transcript: str = "What is photosynthesis?") -> None:
        self.transcript = transcript
        self.heard: list[tuple[int, str]] = []  # (bytes, content type) of each recording, for tests
        self.spoken: list[str] = []

    async def transcribe(self, audio: bytes, content_type: str) -> Transcript:
        self.heard.append((len(audio), content_type))
        return Transcript(self.transcript, 1.0)

    async def synthesize(self, text: str, fmt: str = "mp3") -> tuple[bytes, str]:
        self.spoken.append(text)
        return tone_wav(min(3.0, max(0.3, 0.09 * len(text)))), "audio/wav"

    async def aclose(self) -> None:
        return None
