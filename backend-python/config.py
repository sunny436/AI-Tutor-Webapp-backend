"""
config.py
---------
The "control panel" for the Python AI backend. It reads settings from the
.env file so you never hard-code keys or URLs in the code.

This backend attaches to the Convex template as the "domain/AI" backend:
Convex proxies a job to us, we run the Ayurveda/Yoga flow, then we send the
answer back to Convex via a webhook.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


# ---- Which AI provider to use ----
# "openrouter" (many models behind one key), "groq" (free tier), "ollama" (local)
LLM_PROVIDER = _get("LLM_PROVIDER", "openrouter").lower()

# OpenRouter = one key, one OpenAI-compatible endpoint, ~340 models. Chosen as
# the default because it lets each role use the model that suits it and lets the
# fallback chain span providers, so no single vendor outage stops the assistant.
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = _get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# Sent as HTTP-Referer / X-Title so spend is attributable in the dashboard.
OPENROUTER_SITE_URL = _get("OPENROUTER_SITE_URL", "http://localhost:3000")
OPENROUTER_APP_NAME = _get("OPENROUTER_APP_NAME", "Ayurveda & Yoga Assistant")

# Groq = free cloud API (kept as an alternative provider)
GROQ_API_KEY = _get("GROQ_API_KEY", "")
GROQ_MODEL = _get("GROQ_MODEL", "llama-3.3-70b-versatile")

# Ollama = free local option (optional)
OLLAMA_MODEL = _get("OLLAMA_MODEL", "llama3.2")
OLLAMA_BASE_URL = _get("OLLAMA_BASE_URL", "http://localhost:11434")

# ---- Model roles ----
# Two roles, because they have genuinely different requirements, and both were
# chosen from measurements rather than reputation. `scripts/eval_models.py`
# scores candidates on this project's own prompts; results that decided it:
#
#   RESPONDER (10 axes: json, plan, headings, safety, grounded, hinglish,
#              devanagari, translate, summarise, expand)
#     google/gemini-2.5-flash    10/10   41s   $0.0054   <- chosen
#     deepseek/deepseek-v3.2      9/10   33s   $0.0031   (answered Hinglish wrong)
#     qwen/qwen3.5-plus-02-15     9/10  184s   $0.0243   (summary not shorter)
#     anthropic/claude-haiku-4.5  8/10   42s   $0.0265   (missed exact headings)
#     openai/gpt-5-mini           7/10  106s   $0.0144   (no JSON under a cap)
#
#   ROUTER (json, plan)
#     google/gemini-2.5-flash-lite       2/2   4.9s   <- chosen, 2.5x the fastest
#     mistralai/mistral-small-3.2-24b    2/2  12.1s
#     qwen/qwen3.7-flash                 0/2   — spends the cap on reasoning
#     openai/gpt-5-nano                  0/2   — same
#
# The router's latency is what the user feels first: nothing happens on a turn
# until it returns, so speed outranks the fraction of a cent it saves.
#
# ---- FREE-ONLY, measured by scripts/eval_free_models.py ----
# Every paid model was removed. The four tests are the ones that actually break
# this product: JSON under the router token cap, section headings reproduced
# character for character, an English question answered in English despite
# Hinglish notes, and never naming a medicine.
#
#   nvidia/nemotron-3-nano-30b-a3b:free      4/4   4.6s   <- chosen for both roles
#   google/gemma-4-26b-a4b-it:free           4/4  16.0s   <- fallback 1
#   nvidia/nemotron-3-super-120b-a12b:free   4/4  18.7s   <- fallback 2
#   nvidia/nemotron-nano-9b-v2:free          3/4  10.8s   - returned empty JSON
#   openrouter/free                          3/4  15.1s   - 0/4 headings, unusable
#   openai/gpt-oss-20b:free                  3/4  20.2s   - rate-limited mid-run
#   nvidia/nemotron-3-ultra-550b-a55b:free   3/4  33.4s   - named "antacid"
#   google/gemma-4-31b-it:free               0/4          - 429 on every call
#
# `openrouter/free` scoring 0/4 on headings is the one to remember: it would
# render a completely blank answer, because AnswerSections drops anything whose
# heading it cannot match exactly.
#
# The winner is also the fastest, which settles the usual quality-vs-latency
# argument - there is nothing to trade here.
PRIMARY_MODEL = _get("PRIMARY_MODEL", "nvidia/nemotron-3-nano-30b-a3b:free")
ROUTER_MODEL = _get("ROUTER_MODEL", "nvidia/nemotron-3-nano-30b-a3b:free")
# Tried in order when the primary is out of quota, spanning three vendors so one
# provider outage cannot take out the chain. Ordered by measured score, then cost.
# Claude and GPT-5-mini are deliberately absent: one failed the exact heading
# strings the UI colour-codes, the other cannot emit JSON under a token cap.
# All three scored 4/4. Ordered by measured latency.
#
# An honest limitation: only NVIDIA and Google ship free models that pass all
# four tests, so this chain spans two vendors rather than three. It survives a
# model being rate-limited - the common case on a free tier - but a full NVIDIA
# outage would leave one option instead of two.
MODEL_CHAIN = _get(
    "MODEL_CHAIN",
    "nvidia/nemotron-3-nano-30b-a3b:free,"
    "google/gemma-4-26b-a4b-it:free,"
    "nvidia/nemotron-3-super-120b-a12b:free",
)

# ---- Voice ----
# Speech in and speech out run on the SAME OpenRouter key as everything above -
# there is one credential for the whole stack, not a separate speech vendor.
#
# STT is a chain for the same reason MODEL_CHAIN is: the free tier is the right
# default but is the first thing to rate-limit, so a paid model stands behind it.
# Both are multimodal chat models rather than a dedicated transcription service,
# which is what lets them return the DETECTED LANGUAGE alongside the transcript -
# a plain speech-to-text endpoint would give the words and nothing else, and the
# language is the whole reason a spoken Hindi question gets a Hindi answer.
# Speech IN is free: `nemotron-omni` is the ONLY free model on OpenRouter that
# accepts audio, and it is already the primary. The paid fallback was removed
# with the rest, so a rate-limited transcription now fails rather than costing
# money - the mic button reports it and the user can type instead.
STT_MODEL_CHAIN = _get(
    "STT_MODEL_CHAIN",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
)

# Speech OUT has NO free option. Checked against the live catalogue: of 400
# models exactly four emit audio - openai/gpt-audio, openai/gpt-audio-mini, and
# the two google/lyria models, which generate MUSIC, not speech. The two that
# can read text aloud are both paid.
#
# So TTS is OFF by default. The "Listen" button reports that it is unavailable
# rather than silently spending money on a key that is meant to be free-only.
# To turn it back on, set TTS_MODEL=openai/gpt-audio-mini in .env and accept
# ~$0.005 per answer read aloud.
TTS_MODEL = _get("TTS_MODEL", "")
TTS_VOICE = _get("TTS_VOICE", "alloy")
TTS_ENABLED = bool(TTS_MODEL)
# ~60s of speech is enough to describe a symptom and bounds the per-turn cost.
MAX_AUDIO_SECONDS = int(_get("MAX_AUDIO_SECONDS", "60"))

# Spend guards. A model that fails to stop is billed for everything it emits.
MAX_TOKENS_ROUTER = int(_get("MAX_TOKENS_ROUTER", "400"))
MAX_TOKENS_PLANNER = int(_get("MAX_TOKENS_PLANNER", "1200"))
MAX_TOKENS_ANSWER = int(_get("MAX_TOKENS_ANSWER", "1600"))
LLM_TIMEOUT_SECONDS = float(_get("LLM_TIMEOUT_SECONDS", "60"))

# ---- Ayurveda/Yoga knowledge search (RAG) ----
EMBEDDING_MODEL = _get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
VECTOR_DB_DIR = _get("VECTOR_DB_DIR", "data/vector_store")
KNOWLEDGE_DIR = _get("KNOWLEDGE_DIR", "data/knowledge")

# ---- How this backend connects to the Convex template ----
PORT = int(_get("PORT", "4000"))                       # port this backend runs on
SERVICE_KEY = _get("SERVICE_KEY", "")                  # must match Convex BACKEND_SERVICE_KEY
WEBHOOK_SECRET = _get("WEBHOOK_SECRET", "")            # must match Convex webhook secret
CONVEX_SITE_URL = _get("CONVEX_SITE_URL", "http://localhost:3211")  # Convex "site" URL
CONVEX_AUDIENCE = _get("CONVEX_AUDIENCE", "convex")    # JWT audience for the direct path

# ---- Behaviour ----
MAX_FOLLOWUPS = int(_get("MAX_FOLLOWUPS", "4"))        # legacy /chat: typed follow-ups before answering
# Card-based /consult: how many screens of question cards at most. One round of
# 4-6 cards is the norm; the planner can request a second for a hard case.
MAX_INTAKE_ROUNDS = int(_get("MAX_INTAKE_ROUNDS", "2"))


def is_llm_ready() -> bool:
    """Can this backend actually get an answer out of a model right now?

    The openrouter branch used to `return True` unconditionally, so /health
    reported llm_ready even with an empty key - the one moment the check exists
    for. Free models need a key too: "free" means $0 per token, not no account.

    Ollama is the genuine exception; it runs locally with no credential.
    """
    if LLM_PROVIDER == "groq":
        return bool(GROQ_API_KEY) and GROQ_API_KEY != "your_free_groq_key_here"
    if LLM_PROVIDER == "openrouter":
        return bool(OPENROUTER_API_KEY)
    return True
