"""
config.py
---------
The "control panel" for the Python AI backend. It reads settings from the
.env file so you never hard-code keys or URLs in the code.

RESTORED from the pre-`d7e6d42` architecture, with one change: GraphRAG is
retrieval-only again (`/v1/search`), so its answer-writing settings
(`GRAPHRAG_ANSWER_TIMEOUT_S`) are gone — a local LLM writes every final
answer now, via `src/consult/responder.py::write_plan`.

Also dropped, deliberately, because they were already dead even at the
commit this was restored from: `GROQ_API_KEY`/`GROQ_MODEL` (requirements.txt
had already removed `langchain-groq` — "Groq is gone from the stack
entirely"), `OLLAMA_MODEL`/`OLLAMA_BASE_URL` (the fully-local option —
`llm.py::_build` has no `ollama` branch, only `ollima` the gateway),
`RERANKER_ENABLED` (declared, never read anywhere), `MAX_FOLLOWUPS` (the
legacy single-shot `/chat` flow it belonged to was deleted before this
commit too).
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


# ---- Which AI provider to use ----
# "openrouter" (many models behind one key) or "ollima" (gateway, see below).
# This default barely matters in practice: every MODEL_CHAIN entry below names
# its own provider with a prefix, so this is only the fallback for an
# unprefixed model name.
LLM_PROVIDER = _get("LLM_PROVIDER", "openrouter").lower()

# OpenRouter = one key, one OpenAI-compatible endpoint. Kept for exactly one
# job Ollima cannot do: embeddings (EMBEDDING_MODEL below). No cross-provider
# fallback for chat/reasoning — see the OLLIMA ONLY note further down.
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = _get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# Sent as HTTP-Referer / X-Title so spend is attributable in the dashboard.
OPENROUTER_SITE_URL = _get("OPENROUTER_SITE_URL", "http://localhost:3000")
OPENROUTER_APP_NAME = _get("OPENROUTER_APP_NAME", "Ayurveda & Yoga Assistant")

# Ollima = OpenAI-compatible gateway, one key, several vendors' models behind
# it. Runs the intake, the router and reworks — modest jobs where a fast free
# model is worth more than a strong slow one, now that GraphRAG's own
# retrieval (not a local model) supplies the knowledge context.
OLLIMA_API_KEY = _get("OLLIMA_API_KEY", "")
OLLIMA_BASE_URL = _get("OLLIMA_BASE_URL", "https://api.ollima.com/v1")

# ---- Model roles ----
# OLLIMA ONLY. Chat, the router and every other reasoning call run on OLLIMA.
# OpenRouter is NOT in this chain and is not a fallback for it — it is kept
# for embeddings alone. THERE IS NO CROSS-PROVIDER FALLBACK, by instruction:
# when Ollima is unavailable this product cannot answer at all. That is a
# measured, accepted cost, not an oversight — see git history for the
# account-wide Ollima outage that made the cost concrete rather than
# hypothetical.
PRIMARY_MODEL = _get("PRIMARY_MODEL", "ollima:gemini-3.1-flash-lite")
# The router's latency is what the user feels first — nothing happens on a
# turn until it returns — so the fastest measured model takes this job.
ROUTER_MODEL = _get("ROUTER_MODEL", "ollima:gemini-3.1-flash-lite")
MODEL_CHAIN = _get(
    "MODEL_CHAIN",
    "ollima:gemini-3.1-flash-lite,"
    "ollima:gemini-3.5-flash-low",
)

# Spend guards. A model that fails to stop is billed for everything it emits.
MAX_TOKENS_ROUTER = int(_get("MAX_TOKENS_ROUTER", "800"))
# Devanagari costs far more tokens per character than Latin (measured ~2.6x),
# so a ceiling comfortable in English truncates the JSON mid-object for
# Hindi — this is sized for the worst script, not the average one.
MAX_TOKENS_PLANNER = int(_get("MAX_TOKENS_PLANNER", "2000"))
MAX_TOKENS_ANSWER = int(_get("MAX_TOKENS_ANSWER", "4000"))
LLM_TIMEOUT_SECONDS = float(_get("LLM_TIMEOUT_SECONDS", "60"))

# ---- Ayurveda/Yoga knowledge search (RAG) ----
# Multilingual on purpose — users type romanised Hindi, so the embedder has to
# cover it. Embeddings run on OPENROUTER (baai/bge-m3), not on this machine:
# measured cosine 1.0000 against the same model run locally, so MIN_RELEVANCE
# stays calibrated and nothing needs re-ingesting. What it costs: uploaded
# report text leaves this host to be embedded — a deliberate decision, not a
# default drifted into.
EMBEDDING_MODEL = _get("EMBEDDING_MODEL", "baai/bge-m3")
VECTOR_DB_DIR = _get("VECTOR_DB_DIR", "data/vector_store")
KNOWLEDGE_DIR = _get("KNOWLEDGE_DIR", "data/knowledge")

# ---- Retrieval knobs ----
# Over-fetch, then filter and dedupe down: one note is ~7 chunks, so the
# useful section is not always in the first few.
VECTOR_FETCH_K = int(_get("VECTOR_FETCH_K", "12"))
VECTOR_TOP_K = int(_get("VECTOR_TOP_K", "4"))

# Cosine relevance floor for the curated notes. CALIBRATED PER EMBEDDING
# MODEL — re-measure with scripts/eval_embeddings.py whenever EMBEDDING_MODEL
# changes.
MIN_RELEVANCE = float(_get("KNOWLEDGE_MIN_RELEVANCE", "0.52"))

# Uploaded reports use different vocabulary from a symptom description
# ("serum creatinine" vs "kamzori lag rahi hai") so they need a lower floor
# than the curated notes — but not zero, or an unrelated report reaches the
# prompt.
REPORT_TOP_K = int(_get("REPORT_TOP_K", "4"))
REPORT_MIN_RELEVANCE = float(_get("REPORT_MIN_RELEVANCE", "0.30"))

# Per-retriever budget, and a cap so a wedged source cannot hold up the whole
# consultation. Retrievers run concurrently (asyncio.gather in pipeline.py),
# so this is the worst case for the pipeline, not a per-retriever sum. Every
# Chroma query now embeds the query through OpenRouter first (a network call),
# so this is sized for that round trip, not for a warm local index.
RETRIEVAL_TIMEOUT_S = float(_get("RETRIEVAL_TIMEOUT_S", "8.0"))

# Bounds the embeddings HTTP call inside KnowledgeRetriever and
# UploadedReportsRetriever (both share src/knowledge.py::get_embeddings()).
#
# CONFIRMED, not assumed: with no explicit timeout, langchain_openai defaults
# `request_timeout` to None, and passing `timeout=None` to the openai SDK
# does not mean "use its own default" - it means "disable timeouts entirely"
# (verified directly: openai.OpenAI(timeout=None).timeout is None, versus
# openai.OpenAI()'s own default of Timeout(connect=5.0, read=600, ...)). One
# slow OpenRouter response could then block its worker thread indefinitely.
# `asyncio.wait_for`'s own RETRIEVAL_TIMEOUT_S only abandons the ASYNCIO-side
# await - it cannot and does not kill the underlying thread - so the call
# kept running, unreleased, for however long the network actually took.
# Reproduced: 6 concurrent full retrievals (knowledge + GraphRAG together)
# all hit the full 8.0s ceiling, with the knowledge search for every one of
# them still completing well after the pipeline had already given up on it.
# Same "correctness cliff" class of bug GRAPHRAG_TIMEOUT_S already exists to
# prevent for the other retriever - this is the same fix, for this one.
#
# 3.0, not close to RETRIEVAL_TIMEOUT_S: `KnowledgeRetriever._search` can
# make TWO sequential embedding calls in the rare case the topic index and
# the vector store disagree (a note deleted since ingest), so the worst case
# must still land under RETRIEVAL_TIMEOUT_S (8.0) even doubled.
KNOWLEDGE_EMBED_TIMEOUT_S = float(_get("KNOWLEDGE_EMBED_TIMEOUT_S", "3.0"))

# How many independent embeddings clients src.knowledge._PooledEmbeddings
# round-robins across. A SEPARATE issue from the timeout above, found while
# reproducing the reported symptom: one SHARED client's underlying httpx
# connection pool serializes concurrent embed calls somewhere in new-
# connection establishment - measured, 6 concurrent calls through one client
# took 13.46s total even though each individual call finished in under a
# second, while the same 6 calls spread across a small pool of independent
# clients took 1.18s. 6, because that comfortably covers a handful of
# overlapping users/retrievers without holding open more idle keep-alive
# connections than a 3.8 GB host should carry.
KNOWLEDGE_EMBED_POOL_SIZE = int(_get("KNOWLEDGE_EMBED_POOL_SIZE", "6"))

# Is the LOCAL Chroma retriever allowed to ground an answer? GraphRAG is the
# authoritative Ayurveda source; this is the config-only rollback if it
# regresses — no code deploy needed, the vector store stays on disk either
# way. Default 1: a fresh checkout without the vendor credential must not
# silently answer with zero grounding.
LOCAL_RAG_ENABLED = _get("LOCAL_RAG_ENABLED", "1") == "1"

# Is the persistent patient profile on? When off, no profile is loaded or
# saved and nothing extra is asked — the consultation behaves exactly as it
# did before the profile existed.
#
# Default 1, but this is the rollback path that matters most in this feature:
# it changes the first thing a new user is asked, and it depends on Convex
# routes that live in the FRONTEND repo. A backend deployed before those exist
# still works — `patient_profile.load` fails soft to an empty profile — but
# this flag is the way to turn the questioning off outright without a deploy.
# Same config-only rollback precedent as LOCAL_RAG_ENABLED above.
PROFILE_ENABLED = _get("PROFILE_ENABLED", "1") == "1"

# How many earlier turns of THIS conversation may be replayed to the model.
MAX_CONTEXT_MESSAGES = int(_get("MAX_CONTEXT_MESSAGES", "12"))

# Exposes retrieval internals (scores, chunk sources, assembled context) on a
# service-key-guarded debug route. Never enable on a public deployment.
DEBUG_RAG = _get("DEBUG_RAG", "0") == "1"

# ---- GraphRAG (retrieval only — see src/retrieval/graphrag.py) ----
# Credentials come from .env and never from source. The vendor brief that
# carries them, docs/graphrag-api.md, is git-ignored: it holds a live key
# under its own instruction "KEEP SECRET. Do not commit to git."
GRAPHRAG_ENABLED = _get("GRAPHRAG_ENABLED", "0") == "1"
GRAPHRAG_BASE_URL = _get("GRAPHRAG_BASE_URL", "")
GRAPHRAG_PROJECT_ID = _get("GRAPHRAG_PROJECT_ID", "")
GRAPHRAG_API_KEY = _get("GRAPHRAG_API_KEY", "")

# `k` in the /v1/search request body. 6 is the vendor doc's own example.
GRAPHRAG_TOP_K = int(_get("GRAPHRAG_TOP_K", "6"))

# Does GraphRAG actually COVER this question, or is it just returning its
# nearest neighbours? It never returns empty, so without a gate the honest-
# refusal branch in PLAN_PROMPT can never fire. A score threshold alone
# cannot be the gate either — covered/uncovered distributions overlap.
# Coverage needs BOTH: the local alias index claims a note (categorical),
# OR the top passage clears this floor. See GraphRagRetriever.retrieve.
GRAPHRAG_MIN_RELEVANCE = float(_get("GRAPHRAG_MIN_RELEVANCE", "0.65"))

# Kept at or below RETRIEVAL_TIMEOUT_S: a wedged retriever must not hold up a
# consultation. Strictly BELOW it — when they were equal the pipeline's own
# wait_for always fired first and cancelled this coroutine, and
# CancelledError is BaseException on 3.12, so `except Exception` never saw it
# and the failure counter stayed at zero through a complete outage.
#
# RE-MEASURED 2026-08-30 (this reversal), because the 2.5s inherited from an
# earlier measurement was failing every /v1/search call outright: three
# consecutive direct calls (no pipeline wrapper) took 4.39s, 4.95s, 5.48s.
# Whatever "re-measured after the vendor's extractor fix" once meant, it does
# not describe this service today — worth re-checking with the vendor rather
# than assuming either number is still current. 6.5 gives headroom above the
# worst of three, while staying strictly below RETRIEVAL_TIMEOUT_S (8.0).
GRAPHRAG_TIMEOUT_S = float(_get("GRAPHRAG_TIMEOUT_S", "6.5"))

# Path to graphrag-internal-root.crt, passed to httpx as `verify=`. Must
# point OUTSIDE the repo. NEVER set verify=False: the vendor doc is explicit
# that it leaves the connection encrypted but UNAUTHENTICATED, which would
# let anyone on the network read the API key in transit.
GRAPHRAG_CA_BUNDLE = _get("GRAPHRAG_CA_BUNDLE", "")

# ---- Network exposure ----
# `127.0.0.1` means ONLY this machine can connect — Cloudflare Tunnel's
# `cloudflared` runs on this same machine and reaches us over loopback, so
# binding wider buys nothing and costs everything.
HOST = _get("HOST", "127.0.0.1")

# Auto-restart the server when a source file changes. Development only.
RELOAD = _get("RELOAD", "0") == "1"

# Require a valid Convex login token on the endpoints that cost money or CPU
# (/consult and /upload). The app's own UI requires sign-in before the
# consult screen is reachable, so requiring it here costs no real user
# anything, and it is what stands between this backend and anyone on the
# internet spending the quota for everyone else.
REQUIRE_AUTH = _get("REQUIRE_AUTH", "1") == "1"

# Browser origins allowed to call this API. Comma-separated, no wildcards —
# a wildcard cannot be combined with credentials, and auth travels in the
# Authorization header, never a cookie.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in _get("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if origin.strip()
]

# ---- How this backend connects to the Convex template ----
PORT = int(_get("PORT", "4000"))
SERVICE_KEY = _get("SERVICE_KEY", "")                  # must match Convex BACKEND_SERVICE_KEY
WEBHOOK_SECRET = _get("WEBHOOK_SECRET", "")             # must match Convex webhook secret
CONVEX_SITE_URL = _get("CONVEX_SITE_URL", "http://localhost:3211")
CONVEX_AUDIENCE = _get("CONVEX_AUDIENCE", "convex")     # JWT audience for the direct path

# ---- Behaviour ----
# Card-based /consult: how many screens of question cards at most. Prose
# gathering (gathering.py::MAX_GATHERING_ROUNDS) is the live ceiling now;
# this remains for any pre-change conversation still carrying `answers`.
MAX_INTAKE_ROUNDS = int(_get("MAX_INTAKE_ROUNDS", "2"))


def is_llm_ready() -> bool:
    """Can this backend actually get an answer out of a model right now?

    This — not GraphRAG's own readiness — is the real gate for whether a
    consultation can run at all: GraphRAG is one retriever among several and
    fails soft (empty result) when unreachable, but every turn still needs a
    local LLM to route, gather, and write the final answer.
    """
    def _usable(provider: str) -> bool:
        if provider == "openrouter":
            return bool(OPENROUTER_API_KEY)
        if provider == "ollima":
            return bool(OLLIMA_API_KEY)
        return False

    for entry in (m.strip() for m in MODEL_CHAIN.split(",")):
        if not entry:
            continue
        head, separator, rest = entry.partition(":")
        provider = (
            head.lower()
            if separator and rest and head.lower() in ("openrouter", "ollima")
            else LLM_PROVIDER
        )
        if _usable(provider):
            return True

    return _usable(LLM_PROVIDER)


def is_graphrag_ready() -> bool:
    """Is GraphRAG retrieval reachable? Published on /health for visibility —
    NOT the admission gate for /consult (see is_llm_ready)."""
    return GRAPHRAG_ENABLED and bool(GRAPHRAG_BASE_URL and GRAPHRAG_API_KEY)
