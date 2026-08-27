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

# Ollima = OpenAI-compatible gateway, one key, several vendors' models behind it.
# Added because the plan moved to GraphRAG, so our own model now only runs the
# intake, the router and the reworks - modest jobs where a fast free model is
# worth more than a strong slow one.
#
# MEASURED on the intake's JSON task, which is the one that actually matters
# because `gathering.py` needs `response_format: json_object` to come back
# parseable:
#
#     deepseek-v4-flash      4.0s   valid JSON   (free on any plan)
#     gemini-3.1-flash-lite  2.3s   valid JSON
#     gpt-5.6-luna           9.2s   valid JSON
#     glm-5.2               12.4s   BROKEN - wraps it in a ```json fence
#
# glm-5.2 is deliberately not in any chain. `repair.extract_json` would rescue
# the fence, but a model that needs rescuing on every call is the wrong default.
OLLIMA_API_KEY = _get("OLLIMA_API_KEY", "")
OLLIMA_BASE_URL = _get("OLLIMA_BASE_URL", "https://api.ollima.com/v1")

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
# ---- OLLIMA ONLY ----
# Chat, the router and every other reasoning call run on OLLIMA. OpenRouter is
# NOT in this chain and is not a fallback for it. It is kept for exactly two
# jobs Ollima cannot do at all, each documented where it is configured:
# embeddings (EMBEDDING_MODEL) and speech-to-text (STT_MODEL_CHAIN).
#
# THERE IS NO CROSS-PROVIDER FALLBACK, by instruction. The cost is worth stating
# plainly rather than discovering during an outage: when Ollima is unavailable
# this product cannot answer at all, because there is no second provider to
# reach for. That is not hypothetical — Ollima was returning
#   401 "TensorZero authentication error: Database error: pool timed out"
# on every chat call, after hanging for the full timeout, on the morning this
# was written; it recovered a few minutes later. The failure was account-wide,
# identical across every model, which is why a longer chain is not the answer:
# each dead entry costs another LLM_TIMEOUT_SECONDS before the user is told it
# failed, and none of them would have succeeded. Two entries, deliberately.
#
# ---- measured 2026-08-27 by scripts/eval_chain_models.py, on the VM ----
# Router JSON under the token cap, intent classification, and intake questions —
# the two calls that decide whether a consultation happens at all:
#
#   ollima:gemini-3.1-flash-lite    ok  health  4 questions    6.5s  <- primary
#   ollima:gemini-3.5-flash-low     ok  health  4 questions    9.3s  <- fallback
#   ollima:gpt-oss-120b             ok  health  6 questions   21.9s
#   ollima:deepseek-v4-flash        ok  health  6 questions   47.9s
#   ollima:gemma4                   502 on every call — unusable
#
# The two rejects are the useful part of this table. `deepseek-v4-flash` looks
# like the obvious primary from its name and is the WORST choice here: it is a
# reasoning model, so it spends tokens thinking before answering — 129 completion
# tokens for "say ok" under a max_tokens of 5 — and takes 48s to do a job the
# chosen model does in 6.5. It buys 6 intake questions instead of 4 for 7x the
# wait, which is not a trade this product should make; slowness is the complaint
# this project actually gets. `gpt-oss-120b` is the same trade, less extreme, and
# is the one to promote if 4 questions ever proves too thin.
PRIMARY_MODEL = _get("PRIMARY_MODEL", "ollima:gemini-3.1-flash-lite")
# The router's latency is what the user feels first — nothing happens on a turn
# until it returns — so the fastest measured model takes this job.
ROUTER_MODEL = _get("ROUTER_MODEL", "ollima:gemini-3.1-flash-lite")
MODEL_CHAIN = _get(
    "MODEL_CHAIN",
    "ollima:gemini-3.1-flash-lite,"
    "ollima:gemini-3.5-flash-low",
)

# ---- Voice ----
# Speech-to-text stays on OPENROUTER even though chat has moved to Ollima, and
# that is a constraint rather than a preference: Ollima serves no speech model.
# Its /v1/audio/transcriptions returns 404 and its catalogue lists no audio-in
# model, so there is nothing to move this to. Re-check when their catalogue
# grows; until then the mic button needs OpenRouter or it needs to be off.
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
#
# The router's cap was 400 and gemini-2.5-flash-lite hit it exactly — the reply
# was truncated mid-JSON and the turn fell through to the next model. The router
# emits a few dozen tokens of JSON, so 400 was never the real cost control; it
# was a ceiling low enough to clip a model that writes any preamble at all.
# 800 still stops a runaway and costs a fraction of a paisa when unused.
MAX_TOKENS_ROUTER = int(_get("MAX_TOKENS_ROUTER", "800"))
# The planner's cap was 1200, and Devanagari does not fit in it. Measured on
# deepseek-v3.2, the same five-question form for the same complaint:
#
#     english      899 - 915 tokens
#     hinglish     871 - 1000
#     devanagari  1212 - 1248     <- over the cap on every attempt
#
# Devanagari costs far more tokens per character than Latin, so a ceiling that is
# comfortable in English truncates the JSON mid-object for Hindi. The turn then
# failed to parse and fell back to the generic English baseline form, which is
# why Hindi-script users kept getting a plain English questionnaire: not a
# language bug in the planner, a budget too small for their script.
#
# Raising it does not raise the bill. max_tokens is a ceiling, not a reservation,
# so English still stops at ~900 and costs the same. It is strictly cheaper for
# Devanagari, which currently pays for 1200 truncated tokens and then discards
# them. 2000 leaves room for a longer form without being a runaway.
MAX_TOKENS_PLANNER = int(_get("MAX_TOKENS_PLANNER", "2000"))

# The answer cap was left at 1600 when the planner's went up, and the reasoning
# above applies to it MORE, not less. Measured by tokenising the 29 real notes -
# same language, same domain, same section structure as a plan, and literally the
# material a plan is written from:
#
#     chars per token, Hinglish (Latin)     2.76
#     chars per token, Devanagari           1.05      <- 2.6x more expensive
#     the 29 notes            min 1132 / avg 1501 / max 2002 tokens
#
# So the AVERAGE note only just fits under 1600 and the largest does not fit at
# all - in the cheap script. The 1.34x the planner measured was a JSON form,
# mostly English keys with Devanagari only in the values; a plan is almost
# entirely prose in the target script, so it pays the full ratio.
#
# Honest caveat: measured with cl100k_base, which is not the tokenizer
# deepseek/gemini/llama use, and observed plans currently run 2180-2949 chars
# (~800-1070 tokens) without truncating. So this is headroom, not a fix for a
# reproducing failure - `responder._warn_if_incomplete` is what will actually
# tell us if the ceiling ever bites. Raising it costs nothing either way:
# max_tokens is a ceiling, not a reservation.
MAX_TOKENS_ANSWER = int(_get("MAX_TOKENS_ANSWER", "4000"))
LLM_TIMEOUT_SECONDS = float(_get("LLM_TIMEOUT_SECONDS", "60"))

# ---- Ayurveda/Yoga knowledge search (RAG) ----
# Multilingual on purpose. `all-MiniLM-L6-v2` was the old default and is
# ENGLISH-ONLY, which contradicted the retrieval threshold: the MIN_RELEVANCE in
# src/retrieval/knowledge.py documents itself as calibrated against bge-m3, and a
# cosine threshold is only meaningful for the model it was measured on. Users
# here type romanised Hindi, so the embedder has to cover it.
# Embeddings run on OPENROUTER now, not on this machine. Nothing is downloaded
# and no model is held in memory.
#
# THE SWITCH IS EXACT, and that was measured rather than assumed: OpenRouter
# serves `baai/bge-m3`, the identical model this used to run locally, and the
# two agree perfectly — 1024 dimensions both sides, both unit-normalised, and
# the cosine between a local and a remote vector for the same text is 1.0000.
# So MIN_RELEVANCE stays calibrated and vectors already written under the local
# model remain readable. Nothing has to be re-ingested.
#
# What it costs: uploaded medical reports are the only thing embedded, and that
# text now leaves this host. A deliberate decision, not a default to drift into.
#
# What it buys: the 1.9 GB model is gone from a 3.8 GB machine, and the backend
# no longer needs `sentence-transformers` or a warm-up before its first answer.
EMBEDDING_MODEL = _get("EMBEDDING_MODEL", "baai/bge-m3")
VECTOR_DB_DIR = _get("VECTOR_DB_DIR", "data/vector_store")
KNOWLEDGE_DIR = _get("KNOWLEDGE_DIR", "data/knowledge")

# ---- Retrieval knobs ----
# These lived as module constants inside src/retrieval/*, which meant tuning
# retrieval required a code edit and the values could not differ per deployment.
# Defaults below are exactly the previously hard-coded values, so behaviour is
# unchanged until something is set.

# Over-fetch, then filter and dedupe down: one note is ~7 chunks, so the useful
# section is not always in the first few.
VECTOR_FETCH_K = int(_get("VECTOR_FETCH_K", "12"))
VECTOR_TOP_K = int(_get("VECTOR_TOP_K", "4"))

# Cosine relevance floor for the curated notes. CALIBRATED PER EMBEDDING MODEL —
# different models put cosine similarity on different scales, so this must be
# re-measured with scripts/eval_embeddings.py whenever EMBEDDING_MODEL changes.
# See src/retrieval/knowledge.py for the measured score distribution behind 0.52.
MIN_RELEVANCE = float(_get("KNOWLEDGE_MIN_RELEVANCE", "0.52"))

# Uploaded reports use different vocabulary from a symptom description ("serum
# creatinine" vs "kamzori lag rahi hai"), so they need a lower floor than the
# curated notes — but not zero, or an unrelated report reaches the prompt.
REPORT_TOP_K = int(_get("REPORT_TOP_K", "4"))
REPORT_MIN_RELEVANCE = float(_get("REPORT_MIN_RELEVANCE", "0.30"))

# Per-retriever budget, and a cap so a wedged source cannot hold up the whole
# consultation. The retrievers run concurrently (asyncio.gather in pipeline.py),
# so this is the worst case for the pipeline, not a per-retriever sum.
#
# WAS 3.0, and that number came from an assumption this file used to state as
# fact: "Chroma answers in ~50ms warm". It did, while the embedding model ran on
# this machine. It does not now - every Chroma query first embeds the query
# through OpenRouter, over the network.
#
# Measured on the VM, 2026-08-27, embedding baai/bge-m3 through OpenRouter:
#   embed_query alone           0.64  0.72  0.64  0.67  2.05  seconds
#   user_documents.search       0.58  0.60  0.64  0.67  0.68  1.90
# Typical 0.6s, and a spike to 2.0s in six sequential calls with nothing else
# running. Under a real turn every retriever fires at once and shares the loop
# and the link, and 3.0s was duly observed dropping BOTH `uploaded_reports` and
# `previous_conversations` in the same turn - which is how a user with two
# attached reports was told "no documents were attached to your message".
#
# 8.0 is roughly four times the measured spike. Losing a user's own uploaded
# report to an impatient timeout is a far worse failure than waiting.
RETRIEVAL_TIMEOUT_S = float(_get("RETRIEVAL_TIMEOUT_S", "8.0"))

# Is the LOCAL Chroma retriever allowed to ground an answer?
#
# GraphRAG is the authoritative Ayurveda source. This flag exists so that is a
# CONFIG decision with a config rollback, not a code deploy: production sets 0,
# and if GraphRAG regresses, setting 1 and restarting restores full local
# grounding in one line, with the vector store still on disk untouched.
#
# Default is 1, not 0, on purpose. A fresh checkout or a dev machine without the
# vendor credential must not silently answer with zero grounding - it should
# behave the way this repo always did, and production opts out explicitly.
LOCAL_RAG_ENABLED = _get("LOCAL_RAG_ENABLED", "1") == "1"

# No reranker ships today. Declared so the pipeline has a documented switch
# rather than the capability being invisible; a cross-encoder on a CPU-only host
# costs more latency than the relevance it buys on a corpus this size.
RERANKER_ENABLED = _get("RERANKER_ENABLED", "0") == "1"

# How many earlier turns of THIS conversation may be replayed to the model.
MAX_CONTEXT_MESSAGES = int(_get("MAX_CONTEXT_MESSAGES", "12"))

# Exposes retrieval internals (scores, chunk sources, assembled context) on the
# service-key-guarded debug route. Never enable on a public deployment.
DEBUG_RAG = _get("DEBUG_RAG", "0") == "1"

# ---- GraphRAG (external document service) ----
# DECLARATIONS ONLY. Nothing reads these yet — there is no GraphRAG client and no
# retriever. They exist so the later integration adds one file under
# src/retrieval/ instead of also editing config in the same commit.
#
# Credentials come from .env and never from source. The vendor brief that carries
# them, docs/graphrag-api.md, is git-ignored: it holds a live key under its own
# instruction "KEEP SECRET. Do not commit to git."
GRAPHRAG_ENABLED = _get("GRAPHRAG_ENABLED", "0") == "1"
GRAPHRAG_BASE_URL = _get("GRAPHRAG_BASE_URL", "")
GRAPHRAG_PROJECT_ID = _get("GRAPHRAG_PROJECT_ID", "")
GRAPHRAG_API_KEY = _get("GRAPHRAG_API_KEY", "")

# `k` in the /v1/search request body. 6 is the vendor doc's own example.
GRAPHRAG_TOP_K = int(_get("GRAPHRAG_TOP_K", "6"))

# Does GraphRAG actually COVER this question, or is it just returning its nearest
# neighbours? It never returns empty - "stock market kaisa hai" comes back with
# joint-pain passages at 0.0378 - so without a gate the honest-refusal branch can
# never fire, and every off-topic question gets a confident six-section plan.
#
# A score threshold alone CANNOT be that gate. Measured on production-shaped
# Hinglish, the distributions overlap: an uncovered "naak se khoon aata hai"
# scores 0.6005, above six genuinely covered queries.
#
# So coverage is decided by TWO signals, and either one is enough:
#   1. the alias index claims a note  - categorical, 27/28 on a labelled sweep
#   2. the top passage clears this floor - catches a topic we DO cover that the
#      alias index missed on a typo ("nend nhi ati" -> no claim, but 0.6927)
#
# 0.65 sits between the highest uncovered query (naak se khoon, 0.6005) and the
# lowest typo'd covered one (nend nhi ati, 0.6927). Combined: 9/10 on the sweep,
# against 8/10 for the alias alone. Re-measure with the same sweep if the vendor
# changes their embedder - the scale is theirs, not ours.
GRAPHRAG_MIN_RELEVANCE = float(_get("GRAPHRAG_MIN_RELEVANCE", "0.65"))

# Kept at or below RETRIEVAL_TIMEOUT_S above: this is a network-backed retriever
# on an internal host, and a wedged source must not hold up a consultation.
# Strictly BELOW RETRIEVAL_TIMEOUT_S. When they were equal the pipeline's own
# wait_for always fired first and cancelled this coroutine -- and CancelledError
# is BaseException on 3.12, so `except Exception` never saw it and the failure
# counter stayed at zero through a complete outage.
GRAPHRAG_TIMEOUT_S = float(_get("GRAPHRAG_TIMEOUT_S", "2.5"))

# Separate budget for /v1/answer and /v1/answer/stream, because those call a
# model and the 2.5s above would abort every single one of them.
#
# MEASURED on this corpus, 2026-08-25: first token 13.6-18.9s, total 14.7-22.2s
# for a covered question; ~5s when it abstains, because nothing is generated;
# 43.8s worst case, a six-section instruction with no document filter. Scoping
# the call with `document_ids` roughly halves it (39.7s -> 18.1s).
#
# 120s is deliberately far above the worst measurement rather than close to it.
# The frontend allows 180s, so this still fails before the browser gives up and
# the reader sees our error instead of a dead connection.
GRAPHRAG_ANSWER_TIMEOUT_S = float(_get("GRAPHRAG_ANSWER_TIMEOUT_S", "120"))

# Path to graphrag-internal-root.crt, to be passed to httpx as `verify=`. Must
# point OUTSIDE the repo. NEVER set verify=False: the vendor doc is explicit that
# it leaves the connection encrypted but UNAUTHENTICATED, which would let anyone
# on the network read the API key in transit.
GRAPHRAG_CA_BUNDLE = _get("GRAPHRAG_CA_BUNDLE", "")

# ---- Network exposure ----
# Which interface uvicorn binds to. `127.0.0.1` means ONLY this machine can
# connect, which is what we want in production: Cloudflare Tunnel's `cloudflared`
# runs on this same machine and reaches us over loopback, so binding wider buys
# nothing and costs everything — `0.0.0.0` (the old hard-coded value) made the AI
# backend reachable from any device on the LAN, bypassing Cloudflare entirely.
# Override only if the backend must genuinely serve another host.
HOST = _get("HOST", "127.0.0.1")

# Auto-restart the server when a source file changes. Development only.
#
# This used to be hard-coded on, which cost real money in production: uvicorn's
# reloader runs a second process and hands the directory to WatchFiles, and that
# directory contains `.venv` (1.5 GB, tens of thousands of files) and the vector
# store. It burns memory on a machine that is already short of it — which is what
# makes Windows evict the 1.9 GB embedding model between requests, so the next
# visitor waits for it to be paged back in. It also lets any stray file write
# restart the server underneath a live request.
RELOAD = _get("RELOAD", "0") == "1"

# Require a valid Convex login token on the endpoints that cost money or CPU
# (/consult, /upload, /transcribe, /speak).
#
# These used to accept anonymous callers on purpose — the reasoning was that a
# logged-out tab should still be able to ask about turmeric. That was harmless
# while the backend only listened on localhost. Once it is published through
# Cloudflare, the same openness means anybody on the internet can spend the
# free-tier LLM quota, and when that quota is gone the product is down for the
# people who actually signed up. The app's own UI requires sign-in before the
# consult screen is reachable, so requiring it here costs no real user anything.
#
# Set to 0 to restore anonymous access (e.g. for a public demo behind a rate
# limiter).
REQUIRE_AUTH = _get("REQUIRE_AUTH", "1") == "1"

# Browser origins allowed to call this API. The old value was `["*"]`, which let
# ANY website on the internet issue authenticated requests from a victim's browser.
# Comma-separated; the dev default matches the Next.js dev server. In production
# this is set to the real app hostname and nothing else.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in _get("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if origin.strip()
]

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
    def _usable(provider: str) -> bool:
        if provider == "groq":
            return bool(GROQ_API_KEY) and GROQ_API_KEY != "your_free_groq_key_here"
        if provider == "openrouter":
            return bool(OPENROUTER_API_KEY)
        if provider == "ollima":
            return bool(OLLIMA_API_KEY)
        # Ollama runs locally with no credential — the genuine exception.
        return provider == "ollama"

    # MODEL_CHAIN may now name providers per entry ("openrouter:nvidia/...:free"),
    # so readiness is "can ANY model in the chain actually run", not "is the
    # default provider configured". Reporting not-ready because the *default*
    # provider lacks a key, while a second provider in the chain is fully usable,
    # would take a working assistant offline.
    for entry in (m.strip() for m in MODEL_CHAIN.split(",")):
        if not entry:
            continue
        head, separator, rest = entry.partition(":")
        provider = (
            head.lower()
            if separator and rest and head.lower() in ("groq", "openrouter", "ollima", "ollama")
            else LLM_PROVIDER
        )
        if _usable(provider):
            return True

    # Empty or fully unusable chain — fall back to judging the default provider.
    return _usable(LLM_PROVIDER)
