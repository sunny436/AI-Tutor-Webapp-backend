"""Voice mode (app/voice): the rollout and the student's tutor language checked by every route, before OllaLink
is asked; the limits (media type, size, length, per minute and day, at once, per reply); OllaLink's answers mapped
and retried only when nothing was done; a client that goes away cancels its call; and the chat: a spoken message
tells the tutor and sends the face's expression, a typed one is exactly as before."""

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager

import httpx
import pytest

from app.auth.emails import MemoryEmailSender
from app.chat.assistant import VOICE_TURN, system_prompt_for
from app.db.models import Message
from app.intents.classifier import IntentClassifier
from app.intents.scope import ALLOW_STUDY, ALLOW_SUPPORT, CLARIFY, REDIRECT
from app.llm.fake import FakeProvider
from app.main import create_app
from app.voice.expression import EXPRESSIONS, expression_for
from app.voice.first_speech import first_speakable, settled
from app.voice.provider import FakeVoice, OllalinkVoice, Transcript, VoiceError, build_voice
from app.voice.router import MAX_AUDIO_BYTES, ClientGone, SpeechBudget, _unless_gone
from tests.conftest import make_settings, parse_sse, register
from tests.test_intents import answer as intent_answer
from tests.test_scope import reading as scope_reading

KEY = "sk_test_0123456789abcdefghijklmnopqrstuvwxyz"
AUDIO = b"\x1aE\xdf\xa3" + b"\x00" * 4000  # bytes only: the fake provider hears any recording the same way


@asynccontextmanager
async def voice_app(voice=None, **overrides):
    settings = make_settings(**{"voice_mode": "on", **overrides})
    application = create_app(settings, llm=FakeProvider(), email_sender=MemoryEmailSender(), voice=voice or FakeVoice())
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://t") as client:
            yield application, client


async def transcribe(client, headers, audio=AUDIO, kind="audio/webm", seconds="2.5"):
    return await client.post(
        f"/v1/voice/transcriptions?seconds={seconds}", content=audio, headers={**headers, "Content-Type": kind}
    )


async def speak(client, headers, message_id, text):
    return await client.post("/v1/voice/speech", json={"messageId": message_id, "text": text}, headers=headers)


async def reply_id(client, headers) -> str:
    """A finished reply of the student's own: the message speech may be asked for."""
    response = await client.post("/v1/chat/stream", json={"message": "Explain osmosis"}, headers=headers)
    return next(data["message"]["id"] for name, data in parse_sse(response.text) if name == "done")


async def set_language(client, headers, language: str) -> None:
    response = await client.patch(
        "/v1/learning/preferences", json={"version": 0, "set": {"language": language}}, headers=headers
    )
    assert response.status_code == 200, response.text


# ------------------------------------------------------------------ who it is for
async def test_off_by_default_and_then_nothing_reaches_the_provider():
    voice = FakeVoice()
    async with voice_app(voice, voice_mode="off") as (app, client):
        student = await register(client, app)
        assert (await client.get("/v1/voice", headers=student["headers"])).json() == {
            "enabled": False,
            "ack": False,
            "serverSpeech": False,
        }
        assert (await transcribe(client, student["headers"])).status_code == 404
        message = await reply_id(client, student["headers"])
        assert (await speak(client, student["headers"], message, "Hi.")).status_code == 404
    assert voice.heard == [] and voice.spoken == []
    assert build_voice(make_settings()) is None  # off: no provider, no client made


async def test_qa_only_the_listed_accounts_and_every_route_checks_it_itself():
    voice = FakeVoice()
    async with voice_app(voice, voice_mode="qa", voice_qa_emails="QA@Example.com, other@example.com") as (app, client):
        qa = await register(client, app, email="qa@example.com")
        student = await register(client, app)
        assert (await client.get("/v1/voice", headers=qa["headers"])).json() == {
            "enabled": True,
            "ack": False,
            "serverSpeech": False,
        }
        assert (await client.get("/v1/voice", headers=student["headers"])).json() == {
            "enabled": False,
            "ack": False,
            "serverSpeech": False,
        }
        assert (await transcribe(client, student["headers"])).status_code == 404
        theirs = await reply_id(client, student["headers"])
        assert (await speak(client, student["headers"], theirs, "Hi.")).status_code == 404
        assert voice.heard == [] and voice.spoken == []
        assert (await transcribe(client, qa["headers"])).status_code == 200
    assert len(voice.heard) == 1


async def test_english_only_a_hindi_student_gets_none_of_it():
    voice = FakeVoice()
    async with voice_app(voice) as (app, client):
        english, hindi = await register(client, app), await register(client, app)
        await set_language(client, english["headers"], "english")
        await set_language(client, hindi["headers"], "hindi")
        assert (await client.get("/v1/voice", headers=english["headers"])).json() == {
            "enabled": True,
            "ack": False,
            "serverSpeech": False,
        }
        assert (await client.get("/v1/voice", headers=hindi["headers"])).json() == {
            "enabled": False,
            "ack": False,
            "serverSpeech": False,
        }
        assert (await transcribe(client, hindi["headers"])).status_code == 404
        assert voice.heard == []
        assert (await client.get("/v1/voice")).status_code == 401
        assert (await transcribe(client, {})).status_code == 401


# ------------------------------------------------------------------ speech to text
async def test_a_recording_is_heard_once_and_not_kept():
    voice = FakeVoice("What is photosynthesis?")
    async with voice_app(voice) as (app, client):
        student = await register(client, app)
        response = await transcribe(client, student["headers"], kind="audio/webm;codecs=opus")
        assert response.status_code == 200, response.text
        assert response.json() == {"text": "What is photosynthesis?", "seconds": 1.0}
    assert voice.heard == [(len(AUDIO), "audio/webm")]


async def test_what_a_recording_may_be():
    async with voice_app() as (app, client):
        headers = (await register(client, app))["headers"]
        assert (await transcribe(client, headers, kind="audio/mpeg")).status_code == 415
        assert (await transcribe(client, headers, kind="application/octet-stream")).status_code == 415
        assert (await transcribe(client, headers, kind="audio/ogg")).status_code == 415  # not seen to be accepted
        assert (await transcribe(client, headers, seconds="0")).status_code == 422
        assert (await transcribe(client, headers, seconds="61")).status_code == 422
        empty = await transcribe(client, headers, audio=b"")
        assert empty.status_code == 422 and empty.json()["error"]["code"] == "voice_unreadable"
        # Too big, declared or only counted as it arrives (no Content-Length): refused, never passed on.
        assert (await transcribe(client, headers, audio=b"\x00" * (MAX_AUDIO_BYTES + 1))).status_code == 413

        async def chunks():
            for _ in range(MAX_AUDIO_BYTES // 32_768 + 2):
                yield b"\x00" * 32_768

        streamed = await client.post(
            "/v1/voice/transcriptions?seconds=3", content=chunks(), headers={**headers, "Content-Type": "audio/mp4"}
        )
        assert streamed.status_code == 413
        assert app.state.voice.heard == []


async def test_per_minute_and_per_day_limits_hold_in_the_database():
    async with voice_app(voice_transcriptions_per_minute=2, voice_transcriptions_per_day=3) as (app, client):
        headers = (await register(client, app))["headers"]
        assert [(await transcribe(client, headers)).status_code for _ in range(3)] == [200, 200, 429]
    async with voice_app(voice_transcriptions_per_minute=10, voice_transcriptions_per_day=2) as (app, client):
        headers = (await register(client, app))["headers"]
        assert [(await transcribe(client, headers)).status_code for _ in range(3)] == [200, 200, 429]


class SlowVoice(FakeVoice):
    """Holds every recording until `release` is set: requests at once."""

    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()
        self.entered = [asyncio.Event(), asyncio.Event()]  # the first and the second call are being heard
        self.started = 0

    async def transcribe(self, audio, content_type):
        self.started += 1
        if self.started <= len(self.entered):
            self.entered[self.started - 1].set()
        await self.release.wait()
        return await super().transcribe(audio, content_type)


async def test_at_once_one_per_student_and_a_cap_in_all():
    voice = SlowVoice()
    async with voice_app(voice, voice_transcriptions_in_flight=2) as (app, client):
        first, second, third = [await register(client, app) for _ in range(3)]
        held = asyncio.ensure_future(transcribe(client, first["headers"]))
        await asyncio.wait_for(voice.entered[0].wait(), 5)
        again = await transcribe(client, first["headers"])  # the same student, while theirs is still heard
        assert again.status_code == 429
        other = asyncio.ensure_future(transcribe(client, second["headers"]))
        await asyncio.wait_for(voice.entered[1].wait(), 5)
        busy = await transcribe(client, third["headers"])  # two at once in all: the third is told to wait
        assert busy.status_code == 503 and busy.json()["error"]["code"] == "voice_busy"
        voice.release.set()
        assert (await held).status_code == 200 and (await other).status_code == 200
        assert app.state.voice_calls.total == {"stt": 0, "tts": 0} and app.state.voice_calls.users == {}


async def test_a_client_that_goes_away_cancels_the_call():
    cancelled = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    class Gone:
        async def receive(self):
            await asyncio.sleep(0.05)
            return {"type": "http.disconnect"}

    with pytest.raises(ClientGone):
        await _unless_gone(Gone(), work())
    await asyncio.wait_for(cancelled.wait(), 1)

    class Stays:
        async def receive(self):
            await asyncio.sleep(10)
            return {"type": "http.disconnect"}

    async def quick():
        return Transcript("ok", 1.0)

    assert (await _unless_gone(Stays(), quick())).text == "ok"


# ------------------------------------------------------------------ text to speech
async def test_speech_only_for_the_students_own_reply():
    async with voice_app() as (app, client):
        student, other = await register(client, app), await register(client, app)
        message = await reply_id(client, student["headers"])
        spoken = await speak(client, student["headers"], message, "Osmosis is water moving.")
        assert spoken.status_code == 200, spoken.text
        assert spoken.headers["content-type"] == "audio/wav" and spoken.headers["cache-control"] == "no-store"
        assert spoken.content[:4] == b"RIFF"
        assert (await speak(client, other["headers"], message, "Hi.")).status_code == 404  # not theirs
        for text in ("", "x" * 601):
            assert (await speak(client, student["headers"], message, text)).status_code == 422
        assert app.state.voice.spoken == ["Osmosis is water moving."]


async def test_a_replys_speech_has_a_budget():
    async with voice_app(voice_speech_chars_per_message=600) as (app, client):
        headers = (await register(client, app))["headers"]
        message = await reply_id(client, headers)
        codes = [(await speak(client, headers, message, "a" * 400)).status_code for _ in range(2)]
        assert codes == [200, 429]
    budget = SpeechBudget(10)
    assert budget.spend("m", 6) and budget.spend("m", 4) and not budget.spend("m", 1)


# ------------------------------------------------------------------ OllaLink
def ollalink(handler) -> OllalinkVoice:
    return OllalinkVoice(
        "https://gpu-transcribe.test", "https://gpu-tts.test", KEY, "hadley", transport=httpx.MockTransport(handler)
    )


async def test_ollalink_speech_to_text_as_documented():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": " What  is\nosmosis? ", "language": "en", "duration": 2.4})

    provider = ollalink(handler)
    transcript = await provider.transcribe(AUDIO, "audio/webm")
    await provider.aclose()
    assert transcript == Transcript("What is osmosis?", 2.4)
    (request,) = seen
    assert str(request.url) == "https://gpu-transcribe.test/v1/audio/transcriptions"
    assert request.headers["X-NH-GPU-Key"] == KEY
    body = request.read()
    assert b'name="language"\r\n\r\nen' in body and b'filename="utterance.webm"' in body


async def test_ollalink_text_to_speech_as_documented():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"ID3mp3", headers={"Content-Type": "audio/mpeg"})

    provider = ollalink(handler)
    assert await provider.synthesize("Hello there.") == (b"ID3mp3", "audio/mpeg")
    await provider.aclose()
    assert str(seen[0].url) == "https://gpu-tts.test/v1/audio/speech"
    assert json.loads(seen[0].content) == {
        "input": "Hello there.",
        "language": "en",
        "voice": "hadley",
        "response_format": "mp3",
    }


def text_ok() -> httpx.Response:
    return httpx.Response(200, json={"text": "Hi", "duration": 1})


def mp3_ok() -> httpx.Response:
    return httpx.Response(200, content=b"ID3", headers={"Content-Type": "audio/mpeg"})


def status(code: int):
    return lambda: httpx.Response(code)


def fails(error: Exception):
    def raise_it():
        raise error

    return raise_it


async def test_retried_once_only_when_nothing_was_done():
    def big_mp3() -> httpx.Response:
        return httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1), headers={"Content-Type": "audio/mpeg"})

    cases = [
        # (lane, answers in turn, outcome, calls made)
        ("stt", (fails(httpx.ConnectError("refused")), text_ok), "ok", 2),  # never sent: tried once more
        ("stt", (fails(httpx.ConnectTimeout("slow connect")), text_ok), "ok", 2),
        ("stt", (status(503), text_ok), "ok", 2),  # the lane's documented "503: retry"
        ("stt", (status(503), status(503)), "unavailable", 2),
        ("stt", (fails(httpx.ReadTimeout("no answer")), text_ok), "unavailable", 1),  # maybe done: never again
        ("stt", (lambda: httpx.Response(400, json={"error": {"code": "bad_audio"}}),), "unreadable", 1),
        ("stt", (status(500),), "unavailable", 1),
        ("stt", (lambda: httpx.Response(200, json={"language": "en"}),), "unavailable", 1),  # no text
        ("tts", (fails(httpx.ConnectError("refused")), mp3_ok), "ok", 2),
        ("tts", (status(503), mp3_ok), "unavailable", 1),  # no documented retry for speech
        ("tts", (fails(httpx.ReadTimeout("no answer")), mp3_ok), "unavailable", 1),
        ("tts", (lambda: httpx.Response(200, json={}),), "unavailable", 1),  # not audio
        ("tts", (big_mp3,), "unavailable", 1),
    ]
    for lane, answers, expected, count in cases:
        calls = []

        def handler(request: httpx.Request, answers=answers, calls=calls) -> httpx.Response:
            calls.append(request)
            return answers[min(len(calls), len(answers)) - 1]()

        provider = ollalink(handler)
        try:
            await (provider.transcribe(AUDIO, "audio/ogg") if lane == "stt" else provider.synthesize("Hello."))
            outcome = "ok"
        except VoiceError as error:
            outcome = error.reason
        finally:
            await provider.aclose()
        assert (outcome, len(calls)) == (expected, count), (lane, expected)


async def test_the_key_and_the_words_never_reach_a_log(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        if "speech" in str(request.url):
            return mp3_ok()
        return httpx.Response(200, json={"text": "my secret question", "duration": 1})

    async with voice_app(ollalink(handler)) as (app, client):
        logging.getLogger().addHandler(caplog.handler)  # create_app replaced the root's handlers
        caplog.set_level(logging.INFO, logger="app.voice")
        headers = (await register(client, app))["headers"]
        assert (await transcribe(client, headers)).status_code == 200
        message = await reply_id(client, headers)
        assert (await speak(client, headers, message, "a private sentence")).status_code == 200
    logged = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert "voice provider" in logged and "voice transcribed" in logged and "voice spoken" in logged
    for secret in (KEY, "my secret question", "a private sentence"):
        assert secret not in logged


def test_production_refuses_the_fake_and_unsafe_voice_settings():
    base = dict(
        app_env="production",
        secret_key="s" * 40,
        auth_internal_token="t" * 40,
        public_app_url="https://padhai.example",
        app_name="PadhAI",
    )
    for overrides, problem in (
        ({"voice_provider": "fake"}, "VOICE_PROVIDER=fake is not allowed in production"),
        ({"voice_mode": "on", "ollalink_api_key": ""}, "VOICE_MODE needs OLLALINK_API_KEY"),
        ({"voice_mode": "qa", "ollalink_api_key": KEY}, "VOICE_MODE=qa needs VOICE_QA_EMAILS"),
        ({"ollalink_tts_url": "http://gpu-tts.ollalink.com"}, "OLLALINK_TTS_URL must be https://"),
    ):
        with pytest.raises(RuntimeError, match=re.escape(problem)):
            make_settings(**base, **overrides).validate_for_env()
    with pytest.raises(RuntimeError, match="not allowed in production"):
        build_voice(make_settings(app_env="production", voice_mode="on", voice_provider="fake"))


# ------------------------------------------------------------------ the chat
async def stream(client, headers, **body):
    response = await client.post("/v1/chat/stream", json={"message": "Explain osmosis", **body}, headers=headers)
    assert response.status_code == 200, response.text
    return parse_sse(response.text)


def system_prompt(app) -> str:
    return app.state.llm.calls[-1][0].content


async def test_a_spoken_message_tells_the_tutor_and_sends_the_expression_first():
    async with voice_app() as (app, client):
        headers = (await register(client, app))["headers"]
        events = await stream(client, headers, mode="voice")
        assert VOICE_TURN in system_prompt(app)
        names = [name for name, _ in events]
        assert "expression" in names and names.index("expression") < names.index("token")
        (expression,) = [data for name, data in events if name == "expression"]
        assert expression["expression"] == "neutral"  # the router is off: nothing to read
        assert expression["messageId"] == next(data["assistantMessageId"] for name, data in events if name == "meta")
        assert set(expression) == {"messageId", "expression"}


async def test_a_typed_message_is_exactly_as_before():
    """Fresh students, so nothing they have learnt changes the prompt between them."""
    async with voice_app() as (app, client):
        typed, explicit, spoken = [(await register(client, app))["headers"] for _ in range(3)]
        assert all(name != "expression" for name, _ in await stream(client, typed))
        before = system_prompt(app)
        assert all(name != "expression" for name, _ in await stream(client, explicit, mode="text"))
        assert system_prompt(app) == before and VOICE_TURN not in before
        assert any(name == "expression" for name, _ in await stream(client, spoken, mode="voice"))
        assert system_prompt(app).replace(f"\n\n{VOICE_TURN}", "") == before  # one part added, nothing else
        bad = await client.post("/v1/chat/stream", json={"message": "hi", "mode": "video"}, headers=typed)
        assert bad.status_code == 422
    assert system_prompt_for(None) == system_prompt_for(None, voice=False)


async def test_spoken_by_someone_voice_is_not_for_is_a_typed_message():
    async with voice_app(voice_mode="off") as (app, client):
        headers = (await register(client, app))["headers"]
        events = await stream(client, headers, mode="voice")
        assert VOICE_TURN not in system_prompt(app) and all(name != "expression" for name, _ in events)
    async with voice_app() as (app, client):
        headers = (await register(client, app))["headers"]
        await set_language(client, headers, "hinglish")
        events = await stream(client, headers, mode="voice")
        assert VOICE_TURN not in system_prompt(app) and all(name != "expression" for name, _ in events)


# ------------------------------------------------------------------ the face
def test_the_face_follows_the_scope_and_the_router_and_is_neutral_when_unsure():
    def applied(group: str) -> dict:
        return {"applied": True, "group": group, "groupConfidence": 0.9}

    assert expression_for(applied("understand"), ALLOW_SUPPORT, 0.5) == "encouraging"  # worry comes first
    assert expression_for(None, CLARIFY, 0.5) == "thinking"
    assert expression_for(applied("understand"), REDIRECT, 0.5) == "neutral"
    for group, face in (
        ("understand", "explaining"),
        ("materials", "explaining"),
        ("visual_lab", "explaining"),
        ("solve", "focused"),
        ("tests", "focused"),
        ("feedback", "focused"),
        ("planning", "focused"),
        ("language", "neutral"),
        ("no_such_group", "neutral"),
    ):
        assert expression_for(applied(group), ALLOW_STUDY, 0.5) == face
    greeting = {"applied": False, "group": "other", "reason": "other", "groupConfidence": 0.8}
    assert expression_for(greeting, None, 0.5) == "happy"
    assert expression_for({**greeting, "groupConfidence": 0.3}, None, 0.5) == "neutral"  # unsure: neutral
    assert expression_for({"applied": False, "group": "solve", "reason": "low_confidence"}, None, 0.5) == "neutral"
    assert expression_for(None, None, 0.5) == "neutral"
    assert set(EXPRESSIONS) == {"neutral", "happy", "explaining", "focused", "thinking", "encouraging"}


# ------------------------------------------------------------------ latency (2026-10-26)
def test_the_servers_first_words_are_plain_prose_up_to_their_first_pause():
    assert first_speakable(
        "Osmosis is the movement of water molecules, from a dilute solution to a strong one. It"
    ) == (
        43,
        "Osmosis is the movement of water molecules,",
    )
    assert first_speakable("Osmosis is the movement of water molecules, from a") is None  # not yet: ask again
    assert first_speakable("Osmosis [1] is the movement of water across a membrane [2]. It matters.") == (
        59,
        "Osmosis is the movement of water across a membrane.",
    )
    assert first_speakable("Dr. Kalam was a scientist who led India's missile programme for years. He")[0] == 70
    for text in (
        "**Osmosis** is water moving, across a membrane, which matters.",
        "g is 9.8 m/s squared, a lot.",
        "# Osmosis\n",
    ):
        assert first_speakable(text) is None and settled(text)  # the web app reads these itself


LONG = "Explain osmosis, the movement of water across a membrane, in a few simple words please."


def classify(request: httpx.Request) -> httpx.Response:
    """OllaLink's classifier: the scope reads study, the router define_term."""
    (question,) = json.loads(request.content)["questions"]
    return httpx.Response(
        200, json=scope_reading("study") if question == "scope" else intent_answer(question, "define_term")
    )


async def voice_turn(**flags):
    settings = make_settings(voice_mode="on", study_scope="on", intent_router="on", **flags)
    intents = IntentClassifier("https://ai.ollalink.test", KEY, 1.0, 0.5, 0.5, transport=httpx.MockTransport(classify))
    app = create_app(settings, llm=FakeProvider(), email_sender=MemoryEmailSender(), voice=FakeVoice(), intents=intents)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            headers = (await register(client, app))["headers"]
            events = await stream(client, headers, message=LONG, mode="voice", speechFormat="opus")
            reply = next(data["message"]["id"] for name, data in events if name == "done")
            async with app.state.db.sessionmaker() as session:
                metadata = (await session.get(Message, reply)).metadata_
            return events, system_prompt(app), metadata


async def test_parallel_routing_and_the_servers_first_words_change_no_decision():
    events, prompt, metadata = await voice_turn()
    fast_events, fast_prompt, fast_metadata = await voice_turn(voice_parallel_routing="on", voice_server_speech="on")
    assert fast_prompt == prompt  # the same scope line, the same intent line, the same sources
    for key in ("intent", "scope"):
        keep = ("id", "applied", "group") if key == "intent" else ("decision", "best")
        assert {k: fast_metadata[key].get(k) for k in keep} == {k: metadata[key].get(k) for k in keep}
    assert fast_metadata["intent"]["applied"] and fast_metadata["intent"]["id"] == "define_term"
    assert [data["text"] for name, data in fast_events if name == "token"] == [
        data["text"] for name, data in events if name == "token"
    ]
    assert all(name != "speech" for name, _ in events)  # off: nothing is spoken by the server
    names = [name for name, _ in fast_events]
    speech = [data for name, data in fast_events if name == "speech"]
    assert [data["state"] for data in speech] == ["planned", "ready"]
    assert speech[0]["text"] == "You said: Explain osmosis,"  # its first pause 24 characters in or more
    assert speech[0]["chars"] == len(speech[0]["text"]) and speech[1]["audio"] and speech[1]["type"] == "audio/wav"
    assert names.index("speech") > names.index("token") and len(names) - 1 - names[::-1].index("speech") < names.index(
        "done"
    )
