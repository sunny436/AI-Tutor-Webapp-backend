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
    # A plain request timeout (httpx.TimeoutException et al.) had no marker
    # here, so it fell through to `fatal` and raised immediately instead of
    # retrying — the one gap in an otherwise complete classification. Checked
    # AFTER `_EXHAUSTED`, so a provider's own "pool timed out" (an outage
    # dressed as a timeout) still classifies as exhausted, not transient.
    "timeout", "timed out",
)
# Does not clear on its own — drop this model and move down the chain.
#
# "pool timed out" / "database error" are here because a provider dressed its
# own outage as a 401. Ollima returned:
#
#     401 - TensorZero authentication error:
#           Database error: pool timed out while waiting for an open connection
#
# Nothing in that matched any marker, so `_classify` called it FATAL and
# `invoke` gave up on the spot — never reaching the two OpenRouter models
# sitting behind it in the same chain. Measured live: 8 of 8 calls failed, each
# after 60 seconds, and users got the intake question repeated back at them
# because the model never answered.
#
# EXHAUSTED rather than TRANSIENT on purpose. The provider's backend is down,
# not busy: waiting and retrying the same model burns another 60s for the same
# answer, while moving down the chain gets a reply. The cooldown then stops us
# reaching for it again every turn while it is still broken.
_EXHAUSTED = (
    "per day", "tpd", "quota", "insufficient_quota",
    "pool timed out", "database error",
)

# THE REQUEST CAN NEVER SUCCEED AGAINST THIS MODEL, however long we wait — but
# it says nothing about the others, so it must not be `fatal` either.
#
# Measured, live: the gateway lists `gemini-3.5-flash-low` in /models while its
# upstream returns `400 unknown provider for model ... model_not_found`. That
# arrives wrapped in a 502 envelope, so `_TRANSIENT` matched "502" and the
# model was treated as a passing blip: three attempts and 2+4+6s of sleeps
# burned on it EVERY turn, and it stayed permanently in the healthy set,
# ranked ahead of a primary that was merely cooling down.
#
# Worse in the other direction: a bare `400 model_not_found` with no 502
# envelope matched nothing at all and fell through to `fatal`, which RAISES —
# so one wrong model name anywhere in the chain took down the whole service
# instead of being skipped.
#
# Checked before both tables, because this envelope really does contain "502".
_UNAVAILABLE = (
    "model_not_found", "unknown provider", "does not exist", "no such model",
    "not a valid model", "unsupported model", "invalid model",
)

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


KNOWN_PROVIDERS = ("groq", "openrouter", "ollima", "ollama")


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
    if provider == "ollima":
        # Same client as OpenRouter — it is the same wire protocol, just another
        # key and host. No attribution headers: they are an OpenRouter dashboard
        # feature and mean nothing here.
        from langchain_openai import ChatOpenAI

        kwargs = {}
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        return ChatOpenAI(
            model=model,
            api_key=config.OLLIMA_API_KEY,
            base_url=config.OLLIMA_BASE_URL,
            temperature=temperature,
            timeout=config.LLM_TIMEOUT_SECONDS,
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
    # Ollama support was removed rather than left dormant. It ran on this CPU-only
    # machine at ~167s per turn, which is not a usable fallback, and it had been
    # out of the chain for a long time — so it was a provider branch, a dependency
    # and two config knobs that nothing exercised. Dead paths in a fallback ladder
    # are worse than absent ones: they look like safety that is not there.
    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. "
        "Set it to 'openrouter', 'ollima' or 'groq' in .env."
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
    """`unavailable`, `transient` (wait), `exhausted` (next model), or `fatal`."""
    lowered = detail.lower()
    # Checked FIRST: this provider reports a missing model inside a 502
    # envelope, so both of the tables below would otherwise claim it.
    if any(marker in lowered for marker in _UNAVAILABLE):
        return "unavailable"
    # Checked next: a daily-limit message also contains "rate limit", so testing
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
    cooling = [name for name in MODEL_CHAIN if _cooldown.get(name, 0.0) > now]

    # A COOLING MODEL IS DEMOTED, NEVER DROPPED.
    #
    # This used to return `others or [pinned]`, i.e. a model in cooldown was
    # omitted entirely whenever ANY other model was nominally healthy. That is
    # correct while the others work, and indefensible when they do not: with
    # the primary cooling down and the only other chain entry structurally
    # broken, every request failed without the primary being tried even once,
    # and the process stayed that way until someone restarted it. Observed
    # live — a restart, which does nothing but clear this dict, "fixed" it
    # instantly, which is the whole proof that the cooldown was the fault.
    #
    # A cooldown is a guess about the future, and the cheapest way to find out
    # it is wrong is to ask. So cooling models go LAST and are tried only after
    # everything else has genuinely failed. `invoke` gives them a single
    # attempt with no retry ladder, so the guess still saves the time it was
    # meant to save on the turns where it is right.
    if pinned:
        ordered = (
            [pinned, *[n for n in healthy if n != pinned]]
            if _cooldown.get(pinned, 0.0) <= now
            else [*[n for n in healthy if n != pinned], pinned]
        )
        ordered += [n for n in cooling if n != pinned]
    else:
        ordered = [*healthy, *cooling]

    # dict.fromkeys: de-duplicate while keeping the order above. A pinned model
    # that is also in MODEL_CHAIN would otherwise appear twice.
    return list(dict.fromkeys(ordered)) or list(MODEL_CHAIN)


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

    candidates = _available_models(model)
    for position, name in enumerate(candidates):
        # A model still inside its cooldown is being PROBED, not relied on: it
        # is only reached because everything else already failed, so it gets
        # one attempt and no retry ladder. That bounds what the re-probe costs
        # on a turn where the cooldown was right, while still letting the
        # process discover on its own that the model came back.
        probing = _cooldown.get(name, 0.0) > time.monotonic()
        attempts = 1 if probing else MAX_ATTEMPTS
        for attempt in range(1, attempts + 1):
            try:
                client = get_llm(temperature, json_mode, model=name, max_tokens=max_tokens)
                reply = client.invoke(messages)
                if probing:
                    # IT ANSWERED, so the cooldown was wrong and is dropped
                    # here rather than waited out. This is the line that
                    # removes the restart: the next turn puts this model back
                    # at the front of the chain by itself.
                    print(f"[llm] {name} answered while cooling down — cooldown cleared")
                _cooldown.pop(name, None)
                if position:
                    # SAY WHICH MODEL ACTUALLY ANSWERED, when it was not the one
                    # we asked for. The chain is ordered by answer quality, and
                    # its tail is measured at 58s and, for sibling free models,
                    # at "0/4 headings" and one that named a medicine. Until now
                    # a reply from there was indistinguishable from a healthy one
                    # - the return value is a bare string with no attribution, and
                    # nothing downstream records the model - so "the answers got
                    # worse today" had no evidence anywhere to explain it.
                    #
                    # Only logged on a FALLBACK. Logging every success would put a
                    # line on every turn and bury the one that matters.
                    print(
                        f"[llm] answered by {name}, fallback #{position} of "
                        f"{len(candidates) - 1} (first choice: {candidates[0]})"
                    )
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

                if kind == "unavailable":
                    # Structural, and specific to THIS model. Waiting cannot
                    # help, so there is no sleep here — but the others are
                    # untouched, so this must not raise either. Cooling it
                    # stops it outranking a model that is merely resting.
                    _cooldown[name] = time.monotonic() + COOLDOWN_SECONDS
                    print(
                        f"[llm] {name} is not served by the provider "
                        f"({detail[:80]}); skipping to the next model"
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
    # Walk the same healthy-model chain `invoke` uses. Trying only one model and
    # giving up on streaming meant a rate-limited primary sent every reply back
    # to the blocking path, even though a perfectly good second model was sitting
    # right behind it and could have streamed.
    for name in _available_models(model):
        emitted = False
        try:
            client = get_llm(temperature, False, model=name, max_tokens=max_tokens)
            for piece in client.stream(messages):
                text = getattr(piece, "content", "") or ""
                if not text:
                    continue
                emitted = True
                yield text
            if emitted:
                _cooldown.pop(name, None)
                return
        except Exception as error:  # noqa: BLE001 - try the next model, then fall back
            if emitted:
                # Mid-stream failure. The caller already has part of the answer;
                # starting again on another model would rewrite text the reader
                # has seen, so stop and let them keep what arrived.
                print(f"[llm] stream broke after output began: {error}")
                return
            print(f"[llm] {name} could not stream ({str(error)[:120]}); trying the next model")

    # Nothing in the chain could start a stream. `invoke` has the retry ladder,
    # the cooldown bookkeeping and the same fallback order, so hand the whole
    # request to it and emit its answer as one piece — a reader sees the reply
    # arrive at once instead of progressively, and nothing else differs.
    print("[llm] no model could stream; falling back to a single blocking call")
    yield invoke(
        messages,
        temperature=temperature,
        json_mode=False,
        model=model,
        max_tokens=max_tokens,
    )
