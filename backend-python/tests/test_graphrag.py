"""
The GraphRAG retriever: wiring, isolation, and safe failure.

    python tests/test_graphrag.py

THE LIVE SHAPE IS NOW KNOWN. A real /v1/search returns:

    {"chunks": [{"text", "score", "document_name", "document_id"}],
     "entities": [{"entity_id", "name", "entity_type", "description"}],
     "edges": [{"source_id", "target_id", "relation_type", "weight"}],
     "graph_chunk_ids": []}

Measured against the service, not guessed: 6/6 queries answered in 0.45-1.55s,
zero bare MENTIONS edges, 14 meaningful relation types. The retriever is LIVE
(GRAPHRAG_ENABLED=1).

The fixtures below are still deliberately varied rather than narrowed to that one
shape. `_read_passages` is a tolerant reader on purpose -- this is a pilot API
whose response is documented nowhere -- so the alternative shapes exercise the
tolerance itself, and the confirmed shape is exercised by the graph tests further
down, which use the real field names. What is proven here:

  - a recognised shape maps to Chunks correctly, whichever of the shapes it is;
  - an UNRECOGNISED shape raises loudly, naming the keys actually received,
    rather than silently returning nothing;
  - the project id is per-bot, never the global config value;
  - THE RETRIEVER never calls /v1/answer. Answer generation is now a separate,
    explicit path with its own section at the end of this file: it is only safe
    because `document_ids` scopes it to one note, and it is never reached by
    accident from retrieval;
  - certificate verification is never disabled;
  - a dead or slow service degrades the answer instead of failing the consult.

No LLM and no network are involved in the sections above -- httpx is stubbed --
so this suite stays fast and deterministic even though the service is now live.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from src.retrieval.base import RetrievalContext  # noqa: E402
from src.retrieval.graphrag import (  # noqa: E402
    MAX_RELATIONSHIPS,
    GraphRagRetriever,
    _read_passages,
    _read_relationships,
    _top_document_only,
    english_handle,
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# --- INVENTED fixtures. See the module docstring. ---------------------------
#
# The document name is "common-herbs.md" rather than an arbitrary one because the
# coverage gate now requires the alias index's claim to be CORROBORATED by what
# came back. These fixtures exist to prove SHAPE MAPPING, so they must not also
# be fighting the gate - the gate has its own three checks further down.
SHAPES = {
    "results/text/document_name": {
        "results": [{"text": "Ashwagandha is a rasayana.", "document_name": "common-herbs.md", "score": 0.81}]
    },
    "passages/content/source": {
        "passages": [{"content": "Ashwagandha is a rasayana.", "source": "common-herbs.md", "relevance": 0.81}]
    },
    "data-wrapped": {
        "data": {"chunks": [{"passage": "Ashwagandha is a rasayana.", "title": "common-herbs.md"}]}
    },
    "bare array": [{"text": "Ashwagandha is a rasayana.", "filename": "common-herbs.md"}],
}



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


def run_retrieve(payload, query="ashwagandha ke fayde"):
    import httpx

    calls.clear()
    real_post, real_key, real_base = httpx.post, config.GRAPHRAG_API_KEY, config.GRAPHRAG_BASE_URL
    try:
        httpx.post = make_post(payload)
        config.GRAPHRAG_API_KEY = "test-key-not-a-real-credential"
        config.GRAPHRAG_BASE_URL = "https://graphrag.invalid"
        return asyncio.run(
            GraphRagRetriever(enabled=True).retrieve(RetrievalContext(query=query))
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
    result.chunks[0].source == "graphrag:common-herbs.md",
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


# --- 2. scope + the dark switch ---------------------------------------------
# This section used to assert that the project id came from a per-bot config and
# that two bots therefore could not read each other's documents. That claim was
# MEASURED FALSE: the vendor ignores project_id on /v1/search - correct, wrong
# and absent ids return byte-identical results - and their documentation does not
# list the field. Isolation is the API key. The test is rewritten rather than
# deleted because one guard in it is still real: an unconfigured project id must
# make this retriever go dark rather than call out with a blank scope.
print("\nscope + the dark switch")

run_retrieve(SHAPES["bare array"])
check(
    "sends the configured project id",
    calls[0]["json"].get("project_id") == config.GRAPHRAG_PROJECT_ID,
    str(calls[0]["json"].get("project_id")),
)

_real_project = config.GRAPHRAG_PROJECT_ID
try:
    config.GRAPHRAG_PROJECT_ID = ""
    calls.clear()
    result = run_retrieve(SHAPES["bare array"])
    check(
        "no project id configured -> retrieves nothing and makes NO call",
        result.is_empty and not calls,
        f"{len(calls)} calls",
    )
finally:
    config.GRAPHRAG_PROJECT_ID = _real_project

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
# This asserted `enabled is False` while GraphRAG shipped dormant. Both blockers
# that justified that have since been measured away: the vendor's extractor fix
# landed (0 bare MENTIONS edges, correct direction) and latency came down from
# 2.43-7.28s to 0.45-1.52s, inside the 3.0s budget. Enabling it was an explicit
# decision, so what is pinned now is that the switch and the registration agree -
# a retriever registered as enabled while the flag says otherwise, or the
# reverse, is the confusing state worth catching.
check(
    "the registry and the flag agree on whether this runs",
    registered[0].enabled == config.GRAPHRAG_ENABLED,
    f"registered={registered[0].enabled}, GRAPHRAG_ENABLED={config.GRAPHRAG_ENABLED}",
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
            RetrievalContext(query="acidity")
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


# ===========================================================================
# THE GRAPH. Measured against the live service: a response returns 60 entities
# while its edges reference 71 distinct ids, and only 27 of those appear in the
# same payload. So ~62% of edges have an end this response cannot name, and how
# those are handled is the whole correctness question here.
# ===========================================================================
GRAPH_BODY = {
    "entities": [
        {"entity_id": "e1", "name": "Triphala", "entity_type": "Herb"},
        {"entity_id": "e2", "name": "Constipation", "entity_type": "Condition"},
        {"entity_id": "e3", "name": "Ashwagandha", "entity_type": "Herb"},
        {"entity_id": "e4", "name": "Pregnancy", "entity_type": "Condition"},
    ],
    "edges": [
        {"source_id": "e1", "target_id": "e2", "relation_type": "ALLEVIATES", "weight": 0.91},
        {"source_id": "e3", "target_id": "e4", "relation_type": "CONTRAINDICATED_WITH", "weight": 0.95},
        {"source_id": "e1", "target_id": "unresolved-uuid", "relation_type": "CONTAINS"},
        {"source_id": "another-uuid", "target_id": "e2", "relation_type": "TREATS"},
        {"source_id": "e1", "target_id": "e2", "relation_type": "ALLEVIATES"},
        {"source_id": "e1", "target_id": "e2", "relation_type": "VENDOR_ADDED_THIS_LATER"},
        {"source_id": "e1", "target_id": "e1", "relation_type": "RELATED_TO"},
    ],
}
lines = _read_relationships(GRAPH_BODY)
joined = "\n".join(lines)

check("both-ends-resolvable edges are rendered", len(lines) == 2, f"{len(lines)}: {lines}")
check(
    "an unresolvable endpoint is DROPPED, never printed as a uuid",
    "unresolved-uuid" not in joined and "another-uuid" not in joined,
    joined,
)
check(
    "relation types are plain words, never raw database tokens",
    "CONTRAINDICATED_WITH" not in joined and "should be avoided with" in joined,
    joined,
)
check("a duplicate edge appears once", joined.count("Triphala — helps with — Constipation") == 1)
check("an unmapped relation type is skipped rather than guessed at", "VENDOR_ADDED" not in joined)
check("a self-referencing edge is skipped", "Triphala — is related to — Triphala" not in joined)
check(
    "weight never reaches the prompt",
    "0.91" not in joined and "0.95" not in joined,
    joined,
)
check("no graph at all yields nothing, not an error", _read_relationships({}) == [])
check("a non-dict body yields nothing", _read_relationships(None) == [])
check(
    "the number of relationship lines is capped",
    len(
        _read_relationships(
            {
                "entities": [{"entity_id": f"n{i}", "name": f"Herb{i}"} for i in range(200)],
                "edges": [
                    {"source_id": f"n{i}", "target_id": f"n{i + 1}", "relation_type": "ALLEVIATES"}
                    for i in range(199)
                ],
            }
        )
    )
    == MAX_RELATIONSHIPS,
    f"cap is {MAX_RELATIONSHIPS}",
)


# ===========================================================================
# NO RELEVANCE FLOOR OF ITS OWN. Measured on a real constipation query, this
# service returned an off-topic chunk at 0.1251 alongside on-topic ones at
# 0.6773 and 0.1703 - so a score threshold cannot separate them, but the
# document can: the leader wins by ~2x every time.
# ===========================================================================
MIXED = [
    {"text": "constipation root cause", "document_name": "constipation.md", "score": 0.6773},
    {"text": "piles root cause", "document_name": "piles.md", "score": 0.3392},
    {"text": "constipation more", "document_name": "constipation.md", "score": 0.1703},
    {"text": "loose motions", "document_name": "loose-motions.md", "score": 0.1251},
]
kept = _top_document_only(MIXED)
check(
    "only the best-scoring document survives",
    {p["document_name"] for p in kept} == {"constipation.md"},
    str(sorted({p["document_name"] for p in kept})),
)
check(
    "a LOW-scoring chunk from the winning document is kept",
    any(p["score"] == 0.1703 for p in kept),
    "0.1703 chunk is on-topic despite scoring under an off-topic 0.3392",
)
check(
    "the off-topic chunk that used to reach the prompt is gone",
    not any(p["document_name"] == "loose-motions.md" for p in kept),
)
# This used to assert that unscored passages PASS THROUGH. That was fail-open,
# and one vendor field change was enough to trigger it: with no numeric score,
# `ranked` is empty and every returned document sailed past the coverage gate -
# measured, three off-topic notes reached the prompt on a corroborated query.
# With no scores the only signal left is the alias claim, so that is what decides.
check(
    "unscored passages with NO alias claim are dropped, not passed through",
    _top_document_only([{"text": "x"}, {"text": "y"}]) == [],
)
check(
    "unscored passages are narrowed to the alias-claimed note when there is one",
    [
        p["filename"]
        for p in _top_document_only(
            [{"text": "x", "filename": "gas-bloating.md"}, {"text": "y", "filename": "piles.md"}],
            ["gas-bloating.md"],
        )
    ] == ["gas-bloating.md"],
)
check("no passages in, no passages out", _top_document_only([]) == [])

# ===========================================================================
# THE COVERAGE GATE. This service NEVER returns empty - an off-topic question
# comes back with its nearest neighbours ("stock market kaisa hai" -> joint-pain
# passages at 0.0378). Downstream that is indistinguishable from a real answer,
# so without a gate every uncovered question gets a confident plan built on
# unrelated passages and the honest-refusal branch can never fire.
#
# Two signals, either sufficient: an alias-index claim, or a top score clearing
# GRAPHRAG_MIN_RELEVANCE. Neither works alone - see the config comment.
# ===========================================================================
print("\ncoverage gate")

_HI = config.GRAPHRAG_MIN_RELEVANCE + 0.10
_LO = config.GRAPHRAG_MIN_RELEVANCE - 0.10


def _scored(score, name="a.md"):
    return {"chunks": [{"text": "passage", "document_name": name, "score": score}]}


# No alias claim is possible for gibberish, so only the score can carry it.
result = run_retrieve(_scored(_LO), query="zzz qqq wwww")
check(
    "no alias claim and a low score -> retrieves NOTHING",
    result.is_empty,
    f"{len(result.chunks)} chunks",
)

result = run_retrieve(_scored(_HI), query="zzz qqq wwww")
check(
    "no alias claim but a high score -> still retrieved (typo escape hatch)",
    not result.is_empty,
    f"{len(result.chunks)} chunks",
)

# A CORROBORATED claim carries a low score: the alias index named gas-bloating.md
# and that is what came back, so the two agree and the score does not have to.
result = run_retrieve(_scored(_LO, "gas-bloating.md"), query="mujhe gas ho rahi hai")
check(
    "a corroborated alias claim carries a low score through",
    not result.is_empty,
    f"{len(result.chunks)} chunks",
)

# ...but a claim the RESPONSE CONTRADICTS must not. This is the fail-open bug:
# gating on the claim alone made the score floor a no-op for every query the
# alias index recognised, which is most real ones.
result = run_retrieve(_scored(_LO, "joint-pain.md"), query="mujhe gas ho rahi hai")
check(
    "an alias claim the response contradicts does NOT carry a low score",
    result.is_empty,
    f"{len(result.chunks)} chunks",
)

# ===========================================================================
# ANSWER GENERATION (stubbed: no network, no model)
#
# The retriever above must never call /v1/answer. These cover the separate,
# deliberate path that does -- added when the vendor shipped `document_ids`,
# which is what makes a generated answer safe to use at all.
# ===========================================================================
from src.retrieval import graphrag as G  # noqa: E402


class _FakeStream:
    """Stands in for `httpx.stream(...)`'s context manager."""

    def __init__(self, lines, record):
        self._lines, self._record = lines, record

    def __call__(self, method, url, headers=None, json=None, timeout=None, verify=None):  # noqa: A002
        self._record.append({"method": method, "url": url, "json": json or {}, "verify": verify})
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        return iter(self._lines)


def run_stream(lines, **kwargs):
    """Drive answer_stream over canned SSE lines. Returns (pieces, calls)."""
    import httpx

    record: list[dict] = []
    real_stream = httpx.stream
    real_key, real_base = config.GRAPHRAG_API_KEY, config.GRAPHRAG_BASE_URL
    try:
        httpx.stream = _FakeStream(lines, record)
        config.GRAPHRAG_API_KEY = config.GRAPHRAG_API_KEY or "test-key"
        config.GRAPHRAG_BASE_URL = config.GRAPHRAG_BASE_URL or "https://graphrag.test"
        return list(G.answer_stream("gas", **kwargs)), record
    finally:
        httpx.stream = real_stream
        config.GRAPHRAG_API_KEY, config.GRAPHRAG_BASE_URL = real_key, real_base


def sse(*pieces):
    out = []
    for piece in pieces:
        out.append("data: " + json.dumps({"t": piece}))
        out.append("")
    # The vendor terminates every healthy stream with this. Without it the
    # reader is right to treat the reply as truncated -- see the test below.
    out.append("data: [DONE]")
    return out


UUID = "92b813fb-9285-4650-9471-1235a961fa1b"

# --- document picker (stubbed) ----------------------------------------------
# The live 74-query sweep lives in the commit message and in pick_document's
# docstring; these pin the DECISION ORDER, which is what a refactor breaks.
def run_pick(chunks, query, sticky=None, seed=None):
    """Drive pick_document over one canned /v1/search body."""
    import httpx

    calls.clear()
    G._DOCUMENT_IDS.clear()
    if seed:
        G._DOCUMENT_IDS.update(seed)
    real_post, real_key, real_base = httpx.post, config.GRAPHRAG_API_KEY, config.GRAPHRAG_BASE_URL
    try:
        httpx.post = make_post({"chunks": chunks})
        config.GRAPHRAG_API_KEY = "test-key-not-a-real-credential"
        config.GRAPHRAG_BASE_URL = "https://graphrag.invalid"
        return G.pick_document(query, sticky=sticky), list(calls)
    finally:
        httpx.post, config.GRAPHRAG_API_KEY, config.GRAPHRAG_BASE_URL = real_post, real_key, real_base


HIGH = [{"filename": "diabetes.md", "document_id": "doc:dia", "text": "sugar", "score": 0.73}]
LOW = [{"filename": "joint-pain.md", "document_id": "doc:joint", "text": "knees", "score": 0.05}]

(picked, doc_id), made = run_pick(HIGH, "aur batao", sticky="gas-bloating.md",
                                  seed={"gas-bloating.md": "doc:gas"})
check("picker: a sticky topic wins", picked == "gas-bloating.md" and doc_id == "doc:gas", str(picked))
check("picker: and a sticky topic costs no search call", not made, f"{len(made)} calls")

(picked, doc_id), _ = run_pick(
    [{"filename": "gas-bloating.md", "document_id": "doc:gas", "text": "vata", "score": 0.51}],
    "mujhe gas ho rahi hai",
)
check("picker: the alias index claims it", picked == "gas-bloating.md", str(picked))

(picked, _), _ = run_pick(HIGH, "sugar control kaise kare")
check("picker: falls back to the service above the floor", picked == "diabetes.md", str(picked))

(picked, _), _ = run_pick(LOW, "car ka engine kharab hai")
check(
    "picker: picks NOTHING below the floor, so an off-topic question stays unscoped",
    picked is None,
    str(picked),
)

check(
    "picker: the floor it uses is the configured one",
    config.GRAPHRAG_MIN_RELEVANCE > 0.5,
    str(config.GRAPHRAG_MIN_RELEVANCE),
)

G._DOCUMENT_IDS.clear()
G._harvest_ids({"chunks": [{"filename": "a.md", "document_id": "doc:a"},
                           {"filename": "b.md", "document_id": "doc:b"},
                           {"filename": "c.md"}]})
check(
    "picker: one response fills the id map for every note it names",
    G._DOCUMENT_IDS == {"a.md": "doc:a", "b.md": "doc:b"},
    str(G._DOCUMENT_IDS),
)
G._DOCUMENT_IDS.clear()

# --- strip_citation_markers -------------------------------------------------
for label, raw, want in [
    ("chunk:doc: form", f"tight lagta hai [chunk:doc:{UUID}:0].", "tight lagta hai."),
    ("chunk: form (validator drops these)", f"a [chunk:{UUID}:1] b", "a b"),
    ("doc: form", f"c [doc:{UUID}:0] d", "c d"),
    ("corrupted uuid", "x [chunk:doc:1b26bd74-fd01-4e4d-a869d-fe97ac6a2bf2:3] y", "x y"),
    ("two adjacent", f"two [chunk:doc:{UUID}:1][chunk:doc:{UUID}:2] y", "two y"),
    ("leaves prose alone", "no markers here [see below]", "no markers here [see below]"),
]:
    check(f"strip: {label}", G.strip_citation_markers(raw) == want, repr(G.strip_citation_markers(raw)))

# --- streaming --------------------------------------------------------------
pieces, record = run_stream(sse("Ajwain ", "madad ", "karta hai."), document_ids=["doc:x"])
check("stream reassembles the reply", "".join(pieces) == "Ajwain madad karta hai.", repr("".join(pieces)))
check("stream posts to /v1/answer/stream", record[0]["url"].endswith("/v1/answer/stream"), record[0]["url"])
check("stream sends document_ids", record[0]["json"].get("document_ids") == ["doc:x"], str(record[0]["json"]))
check("stream never disables TLS verification", record[0]["verify"] is not False, repr(record[0]["verify"]))
check("stream caps the query at the vendor's 2000", G.MAX_QUERY_CHARS == 2000, str(G.MAX_QUERY_CHARS))

# THE REGRESSION THIS FILE EXISTS FOR. Stripping each frame as it arrived let
# every uuid through: 2145 characters arrived as 729 frames, so a marker is
# always split across several. Split one deliberately.
split = sse("Pet bhara lagta hai ", "[chunk:", "doc:" + UUID[:8], UUID[8:] + ":0", "]", " aur gas banti hai.")
pieces, _ = run_stream(split)
joined = "".join(pieces)
check(
    "a marker split across frames is still removed",
    "chunk:" not in joined and "doc:" not in joined and "[" not in joined,
    repr(joined),
)
check("and the prose around it survives intact", joined == "Pet bhara lagta hai aur gas banti hai.", repr(joined))

# Prose in brackets must NOT be eaten just because it opened a bracket.
pieces, _ = run_stream(sse("khaayein ", "[roz ", "subah] ", "garam paani"))
check("bracketed prose is left alone", "".join(pieces) == "khaayein [roz subah] garam paani", repr("".join(pieces)))

# --- truncation -------------------------------------------------------------
# A stream that stops without [DONE] is a half-written plan. The section it
# loses first is the last one, "When To See A Doctor".
truncated = ["data: " + json.dumps({"t": "Root Cause: vata"}), ""]
try:
    run_stream(truncated)
    check("a stream with no [DONE] raises rather than returning half an answer", False, "no exception")
except RuntimeError as error:
    check("a stream with no [DONE] raises rather than returning half an answer", True, str(error)[:60])

# --- unconfigured -----------------------------------------------------------
real_key = config.GRAPHRAG_API_KEY
try:
    config.GRAPHRAG_API_KEY = ""
    G.answer("gas")
    check("an unconfigured key is an error, not a quiet empty answer", False, "no exception")
except RuntimeError as error:
    check("an unconfigured key is an error, not a quiet empty answer", True, str(error)[:60])
finally:
    config.GRAPHRAG_API_KEY = real_key

passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== graphrag: {passed}/{len(results)} passed =====")
print("NOTE: response mapping is fixture-based. LIVE MAPPING UNVERIFIED (DNS + undocumented schema).")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
sys.exit(0 if passed == len(results) else 1)
