"""
llm.py
------
Returns a ready-to-use AI model, and runs calls against it with the retry and
fallback policy every caller needs.

The model client is CACHED per (model, temperature, json_mode) so we don't
rebuild it on every message.

`json_mode=True` asks the provider to guarantee syntactically valid JSON. The
intake planner relies on it: it removes most malformed-output failures at the
source, so `src/consult/repair.py` only has to handle the semantic slips
(duplicate ids, too many questions) rather than broken syntax.

WHY `invoke()` EXISTS
Groq returns 429 for two situations that must not be handled the same way:

  per MINUTE   clears in seconds. Waiting is the correct response; failing the
               turn throws away a request that was about to succeed.
  per DAY      does not clear for hours. Retrying just burns the request timeout
               before showing the user the same message.

So transient limits are slept through, and a genuinely exhausted model is
dropped for a cooldown while the next model in the chain takes over. Every model
carries its own separate daily budget, which is the point: measured on this
account, llama-3.3-70b allows 12,000 TPM / 1,000 requests a day and
gpt-oss-120b another 8,000 / 1,000. Chaining them multiplies the usable budget
instead of showing the red daily-limit banner the first time one runs dry.

Only once every model is exhausted does the error reach `consult/router.py`,
which turns it into that banner.
"""

import re
import time

import config

_cache: dict = {}

# Tried in order. Ordered by answer quality, not speed — the fallbacks exist to
# keep the assistant working on a bad day, not to serve the common path.
MODEL_CHAIN: list[str] = [name.strip() for name in config.MODEL_CHAIN.split(",") if name.strip()]

# Clears on its own — wait and retry the same model.
#
# "429", "rate-limited" and "temporarily" were added after the switch to free
# models, and their absence was doing real damage. A free-tier refusal reads:
#
#     "google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream"
#
# which contains none of the original markers - no "per minute", no "tpm", no
# "503". So `_classify` called it FATAL and `invoke` re-raised immediately:
# no wait, no retry, and no move to the next model. The fallback chain was
# there but unreachable for the single most common failure a free tier has.
#
# It showed up as whole conversations starting empty, which then failed later
# assertions ("in Hindi" answered with the off-topic refusal) and looked like
# a model-quality problem rather than a dropped request.
_TRANSIENT = (
    "per minute", "tpm", "rpm", "429", "rate-limited", "rate limited",
    "temporarily", "503", "502", "overloaded", "service unavailable",
    "capacity", "try again",
)
# Does not clear on its own — drop this model and move down the chain.
_EXHAUSTED = ("per day", "tpd", "quota", "insufficient_quota")

# Groq states its own backoff: "Please try again in 6.913s" / "in 2m30.5s".
_RETRY_AFTER = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s")

MAX_ATTEMPTS = 3
# Past this, moving to the next model beats making the user wait.
MAX_WAIT_SECONDS = 20.0
# A daily quota lasts hours, but a server running for days has to recover on its
# own, so this is a cooldown rather than a permanent write-off.
COOLDOWN_SECONDS = 900.0

# model -> monotonic time before which it must not be tried again.
_cooldown: dict[str, float] = {}


KNOWN_PROVIDERS = ("groq", "openrouter", "ollama")


def split_provider(name: str) -> tuple[str, str]:
    """`"groq:llama-3.3-70b"` -> `("groq", "llama-3.3-70b")`.

    Lets ONE chain span providers, which is the whole point: Groq meters tokens
    per day per model, so once its two capable models are spent the assistant is
    down for the day no matter how the Groq-side chain is ordered. A second
    provider is separate capacity, not just another model.

    Splits on the first colon ONLY when what precedes it names a known provider.
    OpenRouter ids legitimately contain colons — `nvidia/nemotron-3-nano-30b-a3b:free`
    — and a naive `split(":")` would mangle every one of them into a bogus
    provider and a truncated model.

    An unprefixed name keeps working exactly as before, taking LLM_PROVIDER, so
    existing configs and the Ollama path are untouched.
    """
    head, separator, rest = name.partition(":")
    if separator and rest and head.lower() in KNOWN_PROVIDERS:
        return head.lower(), rest
    return config.LLM_PROVIDER, name


def _build(model: str, temperature: float, json_mode: bool, max_tokens: int = 0):
    provider, model = split_provider(model)
    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        kwargs: dict = {}
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        return ChatOpenAI(
            model=model,
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
            temperature=temperature,
            timeout=config.LLM_TIMEOUT_SECONDS,
            # Attribution headers. OpenRouter uses them to label traffic in the
            # dashboard, which is the only way to see per-app spend on a key.
            default_headers={
                "HTTP-Referer": config.OPENROUTER_SITE_URL,
                "X-Title": config.OPENROUTER_APP_NAME,
            },
            **kwargs,
        )
    if provider == "groq":
        from langchain_groq import ChatGroq

        kwargs = {}
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        return ChatGroq(
            model=model,
            api_key=config.GROQ_API_KEY,
            temperature=temperature,
            **kwargs,
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=config.OLLAMA_MODEL,
            base_url=config.OLLAMA_BASE_URL,
            temperature=temperature,
            **({"format": "json"} if json_mode else {}),
        )
    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. Set it to 'openrouter', 'groq' or "
        "'ollama' in .env."
    )


def get_llm(
    temperature: float = 0.4,
    json_mode: bool = False,
    model: str = "",
    max_tokens: int = 0,
):
    """Return a cached chat model for the given model / temperature / output mode."""
    name = model or config.PRIMARY_MODEL
    key = (name, round(float(temperature), 2), bool(json_mode), int(max_tokens))
    if key not in _cache:
        _cache[key] = _build(name, temperature, json_mode, max_tokens)
    return _cache[key]


def _classify(detail: str) -> str:
    """`transient` (wait), `exhausted` (next model), or `fatal` (give up)."""
    lowered = detail.lower()
    # Checked first: a daily-limit message also contains "rate limit", so testing
    # the transient markers first would sleep on an error that never clears.
    if any(marker in lowered for marker in _EXHAUSTED):
        return "exhausted"
    if any(marker in lowered for marker in _TRANSIENT):
        return "transient"
    return "fatal"


def _retry_delay(detail: str, attempt: int) -> float | None:
    """Seconds to wait, or None when waiting is not worth it."""
    match = _RETRY_AFTER.search(detail)
    # Trust the provider's own figure when it gives one; otherwise back off gently.
    wait = (
        int(match.group(1) or 0) * 60 + float(match.group(2)) + 0.5
        if match
        else 2.0 * attempt
    )
    return wait if wait <= MAX_WAIT_SECONDS else None


def _available_models(pinned: str) -> list[str]:
    """The chain to try, skipping anything still cooling down.

    A pinned model is a PREFERENCE, not a restriction. It used to return
    `[pinned]` and nothing else, which turned the caller into a single point of
    failure: the router pins its model, so when that one model hit its daily
    token limit every consultation failed with the red daily-limit banner —
    while another model in the chain was healthy, idle, and carrying its own
    separate daily budget.

    That defeats the entire reason MODEL_CHAIN exists (see the module docstring:
    chaining multiplies the usable free budget instead of dying when the first
    model runs dry). Measured case: llama-3.3-70b at TPD 99338/100000 while
    gpt-oss-120b answered the same router prompt correctly and instantly.

    The original intent — don't spend the good model's budget on classification —
    is preserved, because the pinned model is still tried FIRST every time.
    """
    now = time.monotonic()
    healthy = [name for name in MODEL_CHAIN if _cooldown.get(name, 0.0) <= now]

    if pinned:
        others = [name for name in healthy if name != pinned]
        # Known-exhausted: skip it rather than burning a doomed request per turn.
        # It comes back the moment its cooldown lapses, and it is still the
        # last resort if nothing else is left.
        if _cooldown.get(pinned, 0.0) > now:
            return others or [pinned]
        return [pinned, *others]

    # Everything is cooling down. Try them all anyway rather than fail without
    # making a single request — a cooldown is a guess, not a fact.
    return healthy or list(MODEL_CHAIN)


def invoke(
    messages,
    *,
    temperature: float = 0.4,
    json_mode: bool = False,
    model: str = "",
    max_tokens: int = 0,
) -> str:
    """Run one chat completion, retrying transient limits and falling back on dead models.

    `model` pins a single model and disables the chain — used by the router,
    which wants the cheap high-request-budget model rather than the best one.

    `max_tokens` caps the reply. On a metered account this is a spend guard, not
    a formatting preference: without it a model that fails to stop is billed for
    everything it emits.

    Blocking on purpose: every caller already runs this inside
    `asyncio.to_thread`, so the sleeps never touch the event loop.
    """
    last_error: Exception | None = None

    for name in _available_models(model):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                client = get_llm(temperature, json_mode, model=name, max_tokens=max_tokens)
                reply = client.invoke(messages)
                _cooldown.pop(name, None)
                return str(reply.content)
            except Exception as error:  # noqa: BLE001 - re-raised below if nothing works
                last_error = error
                detail = str(error)
                kind = _classify(detail)

                if kind == "exhausted":
                    # Trust the provider's OWN retry figure when it gives one.
                    #
                    # A flat 900s was badly wrong for Groq: its tokens-per-day
                    # bucket refills continuously (~1000/min), so it reports
                    # "try again in 4m32s" and is genuinely usable again by then
                    # — but the model stayed frozen for a further ten minutes,
                    # during which the chain fell through to providers that were
                    # actually dead and the user saw "AI service unavailable"
                    # while a working model sat idle in cooldown.
                    #
                    # Clamped at both ends: never below 30s (or a hard daily cap
                    # would be retried in a hot loop), never above the 900s
                    # backstop (for providers that state no figure at all).
                    match = _RETRY_AFTER.search(detail)
                    stated = (
                        int(match.group(1) or 0) * 60 + float(match.group(2))
                        if match
                        else COOLDOWN_SECONDS
                    )
                    wait = min(max(stated, 30.0), COOLDOWN_SECONDS)
                    _cooldown[name] = time.monotonic() + wait
                    print(
                        f"[llm] {name} is out of quota; retrying in {wait:.0f}s, "
                        "trying the next model meanwhile"
                    )
                    break

                if kind == "fatal":
                    # A bad key or a malformed request fails identically on every
                    # model, so working down the chain would only waste time.
                    raise

                delay = _retry_delay(detail, attempt)
                if delay is None:
                    break
                print(
                    f"[llm] {name} rate-limited, waiting {delay:.1f}s "
                    f"(attempt {attempt}/{MAX_ATTEMPTS})"
                )
                time.sleep(delay)

    raise last_error or RuntimeError("no LLM available")


def stream(
    messages,
    *,
    temperature: float = 0.4,
    model: str = "",
    max_tokens: int = 0,
):
    """Yield the reply in pieces, falling back to `invoke` if streaming fails.

    A generator counterpart to `invoke`, not a replacement: `invoke` still backs
    every caller that needs the whole answer before deciding anything (the
    router, the intake planner, the JSON paths). Only prose shown directly to a
    reader benefits from arriving early.

    Deliberately does NOT duplicate the retry ladder. Once the first token has
    been handed to the caller the reply is already on somebody's screen, so
    silently restarting on a different model would rewrite text they have read.
    Instead: try to stream the preferred model, and if it fails BEFORE emitting
    anything, hand the whole request to `invoke` — which has the full chain,
    cooldown and fallback behaviour — and yield its answer as one piece. The
    reader cannot tell the difference beyond it appearing all at once.

    `json_mode` is absent on purpose. A half-streamed JSON object is not
    parseable, so nothing that needs structure should come through here.
    """
    emitted = False
    try:
        client = get_llm(temperature, False, model=model, max_tokens=max_tokens)
        for piece in client.stream(messages):
            text = getattr(piece, "content", "") or ""
            if not text:
                continue
            emitted = True
            yield text
        if emitted:
            _cooldown.pop(model, None) if model else None
            return
    except Exception as error:  # noqa: BLE001 - fall back below
        if emitted:
            # Mid-stream failure. The caller already has part of the answer;
            # re-running would duplicate it, so stop and let them keep what
            # arrived rather than contradicting the screen.
            print(f"[llm] stream broke after output began: {error}")
            return
        print(f"[llm] streaming unavailable ({error}); falling back to a single call")

    # Either the model streamed nothing at all, or it failed before the first
    # token. Both are safe to retry through the normal path.
    yield invoke(
        messages,
        temperature=temperature,
        json_mode=False,
        model=model,
        max_tokens=max_tokens,
    )


# ======================================================================
#  VOICE
# ======================================================================
# Audio does not go through `invoke()`. LangChain's chat wrapper has no shape for
# an `input_audio` content part or an `audio` response, so these two speak the
# OpenAI-compatible wire format directly. Same key, same base URL, same chain
# discipline - just built by hand instead of through the wrapper.

_TRANSCRIBE_PROMPT = (
    "Transcribe this audio EXACTLY as spoken. Do not translate it, do not "
    "correct the grammar, and do not answer anything in it - the speaker is "
    "talking to somebody else, not to you.\n\n"
    "The speaker is likely to be using Hindi, English, or Hinglish (Hindi spoken "
    "with English words mixed in, written in Latin script). Keep whichever they "
    "used, including the mixing.\n\n"
    'Reply with JSON only: {"text": "<the transcript>", "language": "<one of: '
    'english, hinglish, devanagari>"}\n\n'
    "Pick the language by how the speaker sounds, not by what is easiest to "
    "write: pure English -> english; Hindi with English words mixed in -> "
    "hinglish; Hindi spoken with no English -> devanagari (write it in Hindi "
    "script). If the audio is silent or unintelligible, return an empty text."
)


def _openrouter_post(payload: dict, timeout: float | None = None) -> dict:
    """POST one chat completion to OpenRouter and return the parsed body."""
    import httpx

    response = httpx.post(
        f"{config.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "HTTP-Referer": config.OPENROUTER_SITE_URL,
            "X-Title": config.OPENROUTER_APP_NAME,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout or config.LLM_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _audio_format(mime: str) -> str:
    """Map a browser mime type to the format name the API expects.

    Defaults to wav because that is what the recorder sends: MediaRecorder emits
    webm (or mp4 on Safari), which this API does not accept, so the browser
    re-encodes to WAV before uploading. If that ever changes, this is the line
    that has to change with it.
    """
    lowered = (mime or "").lower()
    if "mp3" in lowered or "mpeg" in lowered:
        return "mp3"
    return "wav"


def transcribe(audio: bytes, mime: str = "audio/wav") -> dict:
    """Speech -> {"text", "language"}, trying each STT model in turn.

    The language is part of the job, not a bonus: it is written straight into the
    conversation's sticky language, so somebody who speaks Hindi gets a Hindi
    reply without having to ask for one.
    """
    import base64
    import json

    encoded = base64.b64encode(audio).decode("ascii")
    payload_messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _TRANSCRIBE_PROMPT},
                {
                    "type": "input_audio",
                    "input_audio": {"data": encoded, "format": _audio_format(mime)},
                },
            ],
        }
    ]

    last_error: Exception | None = None
    for name in [m.strip() for m in config.STT_MODEL_CHAIN.split(",") if m.strip()]:
        try:
            body = _openrouter_post(
                {
                    "model": name,
                    "messages": payload_messages,
                    "temperature": 0,
                    "max_tokens": 800,
                    "response_format": {"type": "json_object"},
                }
            )
            raw = body["choices"][0]["message"]["content"]
            parsed = json.loads(raw)
            text = str(parsed.get("text") or "").strip()
            language = str(parsed.get("language") or "").strip().lower()
            if language not in ("english", "hinglish", "devanagari"):
                language = ""
            return {"text": text, "language": language}
        except Exception as error:  # noqa: BLE001
            # Includes a model that turns out not to accept audio at all, which
            # is exactly the case the chain exists to survive.
            last_error = error
            print(f"[stt] {name} failed: {error}")

    raise last_error or RuntimeError("no speech model available")


# The API streams raw PCM at this rate, and says so nowhere in the response -
# get it wrong and the voice plays back chipmunked or slowed to a drawl.
PCM_SAMPLE_RATE = 24000


def _wav_container(pcm: bytes, sample_rate: int = PCM_SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM in a RIFF/WAVE header.

    Needed because streaming only emits `pcm16` (see `speak`), and a browser
    <audio> element cannot play headerless PCM - it needs a container telling it
    the rate, the channel count and the sample width.
    """
    import struct

    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )


def speak(text: str, voice: str = "") -> dict:
    """Text -> {"audio": <base64 wav>, "format": "wav"}.

    Called only when the user presses the speaker icon. Answers run past 1,500
    characters, so this is trimmed rather than read in full - a plan is meant to
    be skimmed on screen, and billing per output token makes reading the whole
    thing aloud the expensive default.
    """
    import base64
    import json

    import httpx

    clipped = (text or "").strip()[:3000]
    if not clipped:
        return {"audio": "", "format": "wav"}

    payload = {
        "model": config.TTS_MODEL,
        "modalities": ["text", "audio"],
        # Two constraints that are NOT free choices, both discovered by being
        # rejected: audio output requires `stream: true`, and once streaming the
        # only accepted format is `pcm16` - mp3, wav and opus are all refused
        # with "does not support ... when stream=true". So the response arrives
        # as headerless PCM and gets a WAV header put on it below. This is also
        # why `speak` cannot go through `_openrouter_post` like everything else.
        "audio": {"voice": voice or config.TTS_VOICE, "format": "pcm16"},
        "stream": True,
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are a text-to-speech engine, not a conversation "
                    "partner. Read the text below aloud VERBATIM, in the "
                    "language it is written in. Do not reply to it, do not "
                    "greet, do not add or remove anything, and skip markdown "
                    "symbols such as ** and #.\n\n"
                    f"TEXT TO READ:\n{clipped}"
                ),
            }
        ],
    }

    parts: list[bytes] = []
    with httpx.stream(
        "POST",
        f"{config.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "HTTP-Referer": config.OPENROUTER_SITE_URL,
            "X-Title": config.OPENROUTER_APP_NAME,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=max(config.LLM_TIMEOUT_SECONDS, 180.0),
    ) as response:
        if response.status_code != 200:
            response.read()
            raise RuntimeError(f"tts {response.status_code}: {response.text[:300]}")
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            body = line[6:].strip()
            if body == "[DONE]":
                break
            try:
                event = json.loads(body)
            except ValueError:
                # Keep-alive comments sit between events; a non-JSON line is one
                # of those, not a failure.
                continue
            for choice in event.get("choices") or []:
                fragment = (choice.get("delta") or {}).get("audio") or {}
                if fragment.get("data"):
                    # Decode each event separately. Concatenating the base64
                    # TEXT and decoding once would be wrong: any fragment whose
                    # length is not a multiple of three carries "=" padding, and
                    # padding in the middle of a base64 string truncates
                    # everything after it.
                    parts.append(base64.b64decode(fragment["data"]))

    if not parts:
        return {"audio": "", "format": "wav"}
    wav = _wav_container(b"".join(parts))
    return {"audio": base64.b64encode(wav).decode("ascii"), "format": "wav"}
