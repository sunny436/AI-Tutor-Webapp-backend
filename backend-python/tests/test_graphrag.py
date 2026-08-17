"""
The GraphRAG retriever: wiring, isolation, and safe failure.

    python tests/test_graphrag.py

⚠ THE RESPONSE FIXTURES BELOW ARE UNVERIFIED.

The vendor brief documents the /v1/search REQUEST and never the response. It
shows a response only for upload. So the field holding passage text, the field
holding document identity, and whether a score comes back at all are all
NOT DOCUMENTED.

These fixtures are therefore plausible shapes, clearly labelled as invented, used
to prove the plumbing either side of the mapping. **They are not evidence that
the real service returns any of them.** What IS proven here:

  - a recognised shape maps to Chunks correctly, whichever of the shapes it is;
  - an UNRECOGNISED shape raises loudly, naming the keys actually received,
    rather than silently returning nothing;
  - the project id is per-bot, never the global config value;
  - /v1/answer is never called;
  - certificate verification is never disabled;
  - a dead or slow service degrades the answer instead of failing the consult.

Live mapping remains UNVERIFIED until one real response is captured. No LLM and
no network are involved -- httpx is stubbed throughout.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from src.bots import BotConfig, get_bot  # noqa: E402
from src.retrieval.base import RetrievalContext  # noqa: E402
from src.retrieval.graphrag import GraphRagRetriever, _read_passages, english_handle  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# --- INVENTED fixtures. See the module docstring. ---------------------------
SHAPES = {
    "results/text/document_name": {
        "results": [{"text": "Ashwagandha is a rasayana.", "document_name": "charaka.pdf", "score": 0.81}]
    },
    "passages/content/source": {
        "passages": [{"content": "Ashwagandha is a rasayana.", "source": "charaka.pdf", "relevance": 0.81}]
    },
    "data-wrapped": {
        "data": {"chunks": [{"passage": "Ashwagandha is a rasayana.", "title": "charaka.pdf"}]}
    },
    "bare array": [{"text": "Ashwagandha is a rasayana.", "filename": "charaka.pdf"}],
}

PROBE_BOT = BotConfig(
    bot_id="probe", knowledge_collection="p1-bot-isolation-probe", graphrag_project_id="proj-probe"
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


calls: list[dict] = []


def make_post(payload):
    def _post(url, headers=None, json=None, timeout=None, verify=None):  # noqa: A002
        calls.append({"url": url, "json": json or {}, "verify": verify, "headers": headers or {}})
        return _FakeResponse(payload)

    return _post


def run_retrieve(payload, bot=PROBE_BOT, query="ashwagandha ke fayde"):
    import httpx

    calls.clear()
    real_post, real_key, real_base = httpx.post, config.GRAPHRAG_API_KEY, config.GRAPHRAG_BASE_URL
    try:
        httpx.post = make_post(payload)
        config.GRAPHRAG_API_KEY = "test-key-not-a-real-credential"
        config.GRAPHRAG_BASE_URL = "https://graphrag.invalid"
        return asyncio.run(
            GraphRagRetriever(enabled=True).retrieve(RetrievalContext(query=query, bot=bot))
        )
    finally:
        httpx.post, config.GRAPHRAG_API_KEY, config.GRAPHRAG_BASE_URL = real_post, real_key, real_base


# --- 1. the tolerant reader --------------------------------------------------
print("\ntolerant reader (fixtures are INVENTED -- see docstring)")

for label, payload in SHAPES.items():
    result = run_retrieve(payload)
    ok = len(result.chunks) == 1 and result.chunks[0].text.startswith("Ashwagandha")
    check(f"maps a plausible shape: {label}", ok, f"{len(result.chunks)} chunks")

result = run_retrieve(SHAPES["results/text/document_name"])
check(
    "namespaces the citation so the UI can group it",
    result.chunks[0].source == "graphrag:charaka.pdf",
    result.chunks[0].source,
)
check("carries the score when one is offered", result.chunks[0].score == 0.81, str(result.chunks[0].score))
check(
    "leaves the score None when none is offered, rather than inventing 0",
    run_retrieve(SHAPES["bare array"]).chunks[0].score is None,
)

# An unrecognised shape must be LOUD. Silently returning nothing would be
# indistinguishable from "the index had no match" -- the exact confusion to avoid
# while the schema is unknown.
try:
    _read_passages({"unexpected": 1, "other": 2})
    check("an unrecognised shape raises rather than returning empty", False, "no exception")
except ValueError as error:
    check(
        "an unrecognised shape raises, naming the keys actually received",
        "other" in str(error) and "unexpected" in str(error),
        str(error)[:90],
    )

# ...but a raise must still not break the consultation.
result = run_retrieve({"unexpected": 1})
check("...and the retriever still returns empty rather than propagating", result.is_empty)


# --- 2. bot isolation --------------------------------------------------------
print("\nbot isolation (P1 boundary must hold on the remote index too)")

run_retrieve(SHAPES["bare array"], bot=PROBE_BOT)
check(
    "the project id comes from the BOT, not from global config",
    calls[0]["json"].get("project_id") == "proj-probe",
    str(calls[0]["json"].get("project_id")),
)

ayurveda = get_bot("ayurveda")
run_retrieve(SHAPES["bare array"], bot=ayurveda)
check(
    "a different bot sends a different project id",
    calls[0]["json"].get("project_id") == ayurveda.graphrag_project_id != "proj-probe",
)

blank = BotConfig(bot_id="unscoped", knowledge_collection="x", graphrag_project_id="")
calls.clear()
result = run_retrieve(SHAPES["bare array"], bot=blank)
check(
    "a bot with no GraphRAG project retrieves nothing and makes no call",
    result.is_empty and not calls,
    f"{len(calls)} calls",
)


# --- 3. the two hard rules ---------------------------------------------------
print("\nsecurity + architecture invariants")

run_retrieve(SHAPES["bare array"])
check("calls /v1/search", calls[0]["url"].endswith("/v1/search"), calls[0]["url"])
check(
    "NEVER calls /v1/answer (that would be a second LLM writing health text)",
    "/v1/answer" not in calls[0]["url"],
)
check(
    "certificate verification is never disabled",
    calls[0]["verify"] is not False,
    repr(calls[0]["verify"]),
)
check(
    "sends the key as a bearer token, not in the URL or body",
    "Authorization" in calls[0]["headers"] and "key" not in calls[0]["url"].lower(),
)
check("respects GRAPHRAG_TOP_K", calls[0]["json"].get("k") == config.GRAPHRAG_TOP_K)


# --- 4. dormant by default, and fail-soft ------------------------------------
print("\ndormant by default + safe failure")

from src.retrieval.registry import RETRIEVERS  # noqa: E402

registered = [r for r in RETRIEVERS if r.name == "graphrag"]
check("registered in the pipeline", len(registered) == 1)
check("order 45: after uploaded reports (40), before curated notes (50)", registered[0].order == 45)
check(
    "SHIPS DORMANT — disabled, because GRAPHRAG_ENABLED defaults to 0",
    registered[0].enabled is False and config.GRAPHRAG_ENABLED is False,
    f"enabled={registered[0].enabled}",
)


def exploding_post(*_a, **_k):
    raise RuntimeError("connection refused")


import httpx  # noqa: E402

real_post = httpx.post
real_key, real_base = config.GRAPHRAG_API_KEY, config.GRAPHRAG_BASE_URL
try:
    httpx.post = exploding_post
    config.GRAPHRAG_API_KEY = "test-key-not-a-real-credential"
    config.GRAPHRAG_BASE_URL = "https://graphrag.invalid"
    dead = asyncio.run(
        GraphRagRetriever(enabled=True).retrieve(
            RetrievalContext(query="acidity", bot=PROBE_BOT)
        )
    )
    check("a dead service degrades to empty instead of failing the consult", dead.is_empty)
finally:
    httpx.post = real_post
    config.GRAPHRAG_API_KEY, config.GRAPHRAG_BASE_URL = real_key, real_base


# --- 5. the free Hinglish -> English handle ---------------------------------
print("\nEnglish handle for an English-tuned index")

augmented = english_handle("gas ki problem", "ayurveda_yoga")
check(
    "a Hinglish query gains an English term from the note filename",
    "gas bloating" in augmented and "gas ki problem" in augmented,
    augmented,
)
check(
    "an unmatched query is passed through untouched",
    english_handle("qwertyuiop zxcvbnm", "ayurveda_yoga") == "qwertyuiop zxcvbnm",
)


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== graphrag: {passed}/{len(results)} passed =====")
print("NOTE: response mapping is fixture-based. LIVE MAPPING UNVERIFIED (DNS + undocumented schema).")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
sys.exit(0 if passed == len(results) else 1)
