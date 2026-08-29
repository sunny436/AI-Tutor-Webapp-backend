"""
config.py
---------
Settings for the Python backend, read from `.env`.

This backend is a thin proxy now: verify who is asking, run the safety scan,
forward the question to GraphRAG, relay the reply. Every setting below exists
to support exactly that. There is no local model, no local knowledge base and
no local retrieval any more, so none of their settings live here either.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


# ---- GraphRAG (the only source of an answer) ----
# Credentials come from .env and never from source. The vendor brief that
# carries them, docs/graphrag-api.md, is git-ignored: it holds a live key
# under its own instruction "KEEP SECRET. Do not commit to git."
#
# A kill switch, not a retrieval toggle any more: with this off, /consult
# returns 503 rather than attempting a call, matching the "service is not
# configured" response already documented in docs/api-contract.md.
GRAPHRAG_ENABLED = _get("GRAPHRAG_ENABLED", "0") == "1"
GRAPHRAG_BASE_URL = _get("GRAPHRAG_BASE_URL", "")
GRAPHRAG_API_KEY = _get("GRAPHRAG_API_KEY", "")

# `k` in the /v1/answer request body. 6 is the vendor doc's own example.
GRAPHRAG_TOP_K = int(_get("GRAPHRAG_TOP_K", "6"))

# MEASURED on this corpus: first token 13.6-18.9s, total 14.7-22.2s for a
# covered question; 43.8s worst case. 120s sits deliberately far above the
# worst measurement, and below the frontend's own 180s allowance, so a caller
# sees our error rather than a dead connection.
GRAPHRAG_ANSWER_TIMEOUT_S = float(_get("GRAPHRAG_ANSWER_TIMEOUT_S", "120"))

# Path to graphrag-internal-root.crt, passed to httpx as `verify=`. Must point
# OUTSIDE the repo. NEVER set verify=False: the vendor doc is explicit that it
# leaves the connection encrypted but UNAUTHENTICATED, which would let anyone
# on the network read the API key in transit.
GRAPHRAG_CA_BUNDLE = _get("GRAPHRAG_CA_BUNDLE", "")

# ---- Network exposure ----
# `127.0.0.1` means ONLY this machine can connect — Cloudflare Tunnel's
# `cloudflared` runs on this same machine and reaches us over loopback, so
# binding wider buys nothing and costs everything.
HOST = _get("HOST", "127.0.0.1")

# Auto-restart the server when a source file changes. Development only — see
# git history for the incident this being hard-coded on caused in production.
RELOAD = _get("RELOAD", "0") == "1"

# Require a valid Convex login token on /consult and /consult/stream, the
# endpoints that spend GraphRAG's metered quota. The app's own UI requires
# sign-in before the consult screen is reachable, so requiring it here costs
# no real user anything, and it is what stands between this backend and
# anyone on the internet spending the quota for everyone else.
REQUIRE_AUTH = _get("REQUIRE_AUTH", "1") == "1"

# Browser origins allowed to call this API. Comma-separated; the dev default
# matches the Next.js dev server. In production this is set to the real app
# hostname and nothing else — a wildcard here cannot be combined with
# credentials, and auth travels in the Authorization header, never a cookie.
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


def is_graphrag_ready() -> bool:
    """Can this backend actually reach GraphRAG right now?

    Configuration-only, not a live probe — /health calls this on every poll
    and must never be slower or less reliable than the thing it reports on.
    """
    return GRAPHRAG_ENABLED and bool(GRAPHRAG_BASE_URL and GRAPHRAG_API_KEY)
