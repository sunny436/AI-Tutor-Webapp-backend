"""
retrieval/graphrag.py
---------------------
The external GraphRAG document service, as one more retriever.

THE AUTHORITATIVE SOURCE. This is where Ayurveda knowledge comes from, and since
the plan moved to /v1/answer it also WRITES it. The rollback is no longer the
Chroma retriever behind `config.LOCAL_RAG_ENABLED` — it is `consult/offline.py`,
which renders the note's own six sections with no network and no model at all.

⚠ IT IS NOT SELF-SUFFICIENT, AND THAT IS NOT OPTIONAL. Measured over the 74
retrieval cases:

    with the local alias index    73/74
    alias index blinded           48/74

Twenty-five of those cases are carried by `knowledge.match_topics`, through
`english_handle` below - it turns "mujhe gas ho rahi hai" into a query that scores
0.5159 instead of 0.2849 - and through the coverage gate, which needs a claim to
corroborate. So "GraphRAG is the authoritative source" is true about the CONTENT
and false about the mechanism: the local topic index is load-bearing.

Anyone reading LOCAL_RAG_ENABLED=0 and concluding that src/knowledge.py can now be
deleted would drop recall by a third and take the coverage gate down with it. The
vector SEARCH over the notes is retired; the alias index is not.

WHY A RETRIEVER AND NOT A BRANCH IN consult/graph.py
`retrieval/registry.py` states its own contract: adding a knowledge source is one
retriever file plus one line there, and nothing in `src/consult/` changes. This
follows it exactly, so nothing downstream learns that a passage came from a
remote service -- `to_prompt_block` renders it like any other section and
`to_sources` emits a citation for it like any other chunk.

/v1/search FOR RETRIEVAL, /v1/answer FOR THE PLAN — AND WHAT THAT COST
This block used to say `/v1/answer` was never called, because it writes prose
with its own model and has never seen SYSTEM_RULES. That reasoning was right and
the objections are all still true: it cannot be told not to name a medicine, not
to claim to be a practitioner, or to produce our six headings. The vendor
confirmed there is no channel for any of it — the request is `query`, `k`,
`graph_hops`, `exclude_relations`, and one fixed prompt template shared by every
tenant.

It is called anyway, deliberately, because on 2026-08-25 they shipped
`document_ids`. Scoped to a single note the blending stops, and each objection is
answered OUTSIDE their service instead:

  - the six headings travel inside `query` (measured 6/6);
  - `safety.scan` and the gathering red-flag check run above the call, so a
    flagged turn never reaches it;
  - `safety.names_medicine` stays as the backstop;
  - the notes themselves carry the no-self-medication line, so grounding makes
    the model repeat it.

The retriever below still calls ONLY `/v1/search`. Answer generation is a
separate, explicit path — `answer`, `answer_stream` — so nothing reaches the
vendor's model by accident from retrieval.

ISOLATION IS THE API KEY, NOT THE PROJECT ID
This block used to claim the opposite: that reading `config.GRAPHRAG_PROJECT_ID`
instead of a per-bot value would leak one chatbot's documents into another's
answers. That was measured and is FALSE. Sending the correct project id, a wrong
one, and none at all returns byte-identical results -- the vendor ignores the
field on /v1/search, and their own documentation does not list it. The credential
scopes the data, exactly as they intend: one chatbot, one API key, one index.

The id is still sent, because it is harmless and it is what the vendor's upload
path (`/v1/projects/{id}/documents`) takes. It is no longer described as a
security boundary, because it never was one. Anyone holding GRAPHRAG_API_KEY can
read and write this index; that is the whole boundary.

VERIFIED AGAINST THE LIVE SERVICE (2026-08-19)
DNS, TLS against the vendor CA with full hostname checking, authentication, and a
real populated response exercised end to end.

LATENCY, re-measured after the vendor's extractor fix: 0.45-1.55s across six
queries, average 0.71s, none over the 3.0s budget. The 2.43-7.28s figures this
block used to carry were pre-fix and are gone. The budget is still
min(RETRIEVAL_TIMEOUT_S, GRAPHRAG_TIMEOUT_S), and it is now a correctness cliff
rather than a slowdown: with local retrieval off, a timeout costs 100% of the
grounding for that turn. That is what the failure counter in `server.py::health`
exists to make visible.

`_read_passages` remains a TOLERANT READER even though the shape is now known --
the same approach as `apps/app/src/lib/consult/central.ts`. This is a pilot API
whose response is still documented nowhere, so it accepts the shapes such a
service realistically returns and, when it recognises none, raises an error
naming the keys it actually received rather than returning a quiet empty list.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Iterator, Sequence

import config
from src.knowledge import DEFAULT_COLLECTION_NAME, match_topics
from src.retrieval.base import Chunk, RetrievalContext, RetrievalResult
from src.retrieval.pipeline import dedupe

# CONFIRMED against the live service on 2026-08-18. A real /v1/search reply is:
#
#     {"chunks": [], "entities": [], "edges": [], "graph_chunk_ids": []}
#
# so `chunks` is the passage list and is checked first. The rest are kept as
# fallbacks rather than deleted: this is a pilot API, the shape is still not
# written down anywhere, and a reader that survives a rename costs nothing.
#
# `entities`, `edges` and `graph_chunk_ids` are NOT read -- but no longer because
# they are empty. Section 5 of the vendor brief said the knowledge graph was off
# for answering; that is now out of date, confirmed both by the client and by a
# real response carrying 30 entities and 21 edges:
#
#     entity: {"entity_id", "name", "entity_type", "description"}
#     edge:   {"source_id", "target_id", "relation_type": "CAUSES", "weight"}
#
# This is the actual reason to use this service over the local retriever, and it
# is a deliberate open decision rather than an oversight. Feeding relationship
# claims like "X CAUSES Y" into a health prompt changes what the model asserts
# about causation, so it needs a decision and a safety review, not a quiet edit.
_LIST_KEYS = ("chunks", "results", "passages", "matches", "hits", "documents", "items")

# CONFIRMED against a real populated response on 2026-08-18. A chunk is:
#
#     {"chunk_id": "...", "document_id": "doc:<uuid>", "text": "...", "score": 0.43}
#
# so `text` and `score` were already first in their lists and are now facts rather
# than guesses. The alternatives stay as fallbacks for the same reason as above.
_TEXT_KEYS = ("text", "content", "passage", "chunk", "page_content", "body", "snippet")

# CONFIRMED 2026-08-19: the vendor returns `filename`, holding the real note name
# ("constipation.md"), alongside `document_id` ("doc:<uuid>"). An earlier note
# here said document_id was the ONLY identifier and that citations were therefore
# unreadable uuids -- that is no longer true, and `filename` sits second in this
# tuple so it is what a citation actually shows.
#
# `document_id` is kept in the list behind it: it is stable, it is what the
# vendor's delete/retry endpoints take, and it is the fallback if `filename` ever
# stops being sent.
_SOURCE_KEYS = ("document_name", "filename", "source", "title", "document_id", "id")

# `score` confirmed. Note it is NOT on the same scale as the local retriever's
# cosine relevance -- an on-topic passage came back at 0.4336, which would sit
# below `MIN_RELEVANCE` (0.52) if this retriever thresholded. It does not, and
# should not start doing so without measuring this scale properly first.
_SCORE_KEYS = ("score", "relevance", "relevance_score", "similarity")


# Relation types observed on the live service, rendered as plain words.
#
# NEVER shipped raw. "CONTRAINDICATED_WITH" is database jargon: a Hinglish reader
# cannot use it, and a model handed it will repeat the token in its prose. The
# right-hand side is what the sentence should read like once the model puts it in
# an answer.
_RELATION_WORDS = {
    "ALLEVIATES": "helps with",
    "TREATS": "is used for",
    "PACIFIES": "calms",
    "PREVENTS": "helps prevent",
    "RISK_FACTOR": "raises the risk of",
    "AGGRAVATES": "makes worse",
    "SYMPTOM_OF": "is a symptom of",
    "CONTRAINDICATED_WITH": "should be avoided with",
    "INTERACTS_WITH": "interacts with",
    "CONTAINS": "contains",
    "PART_OF": "is part of",
    "PREPARED_AS": "is prepared as",
    "AFFECTS": "affects",
    "RELATED_TO": "is related to",
}

# How many relationship lines may reach the prompt. Six passages already come
# back, and a single response carries ~120 edges -- handing all of them over
# would drown the curated notes, which grounding rule 9 says must stay the
# model's FIRST source. Deliberately small; raise it only with a measurement.
MAX_RELATIONSHIPS = 15


def _read_relationships(body: Any, context: str = "") -> list[str]:
    """Readable "X — verb — Y" lines from the graph, or nothing.

    ⚠ ONLY EDGES WHOSE BOTH ENDPOINTS RESOLVE TO A NAME. Measured against the
    live service: a response returns 60 entities while its edges reference 71
    distinct ids, and only 27 of those appear in the same payload. So roughly
    62% of edges have an end this response cannot name. Emitting them with the
    raw uuid, or inventing a label, would put an unreadable or invented claim
    into a health prompt -- dropping them silently is the honest choice.

    ⚠ AND ONLY EDGES THIS CONSULTATION IS ABOUT. The graph slice that comes back
    is much broader than the query. Observed live: asking about insomnia returned
    "Banana — helps with — Constipation" and "Vitamin B12 — raises the risk of —
    Fatigue and Weakness". None of that is wrong, and all of it is noise in a
    prompt where rule 9 says the curated notes must stay the model's FIRST
    source. `context` is the query plus the retrieved passage text; an edge is
    kept only when one of its two names actually appears there.

    Passing no `context` keeps every resolvable edge, which is what the unit
    tests exercise -- relevance is a separate property from resolvability and is
    easier to reason about tested apart.

    `weight` is deliberately never shown. It is a retrieval signal, not a fact
    about the herb, and a number printed beside a health claim reads as a
    confidence the vendor never offered.
    """
    if not isinstance(body, dict):
        return []

    haystack = (context or "").lower()

    names: dict[str, str] = {}
    for entity in body.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        entity_id, name = entity.get("entity_id"), entity.get("name")
        if isinstance(entity_id, str) and isinstance(name, str) and name.strip():
            names[entity_id] = name.strip()

    lines: list[str] = []
    seen: set[str] = set()
    for edge in body.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = names.get(edge.get("source_id"))
        target = names.get(edge.get("target_id"))
        if not source or not target or source == target:
            continue
        verb = _RELATION_WORDS.get(str(edge.get("relation_type") or "").upper())
        # An unmapped relation type is a vendor change, not something to guess a
        # wording for. Skipped rather than printed raw.
        if not verb:
            continue
        # On topic, or not at all. See the docstring.
        if haystack and source.lower() not in haystack and target.lower() not in haystack:
            continue
        line = f"{source} — {verb} — {target}"
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if len(lines) >= MAX_RELATIONSHIPS:
            break
    return lines


def _top_document_only(passages: list[dict], claimed: list[str] | None = None) -> list[dict]:
    """Passages from the best-scoring document, and nothing else.

    ⚠ THIS SERVICE APPLIES NO RELEVANCE FLOOR OF ITS OWN, and neither did we when
    it was first switched on. The local retriever rejects anything under
    MIN_RELEVANCE (0.52); this one returned everything it found. Measured on a
    real constipation query:

        0.6773  Constipation      on topic
        0.3392  Piles             loosely related
        0.1703  Constipation      on topic
        0.1608  Constipation      on topic
        0.1510  Piles             marginal
        0.1251  Loose motions     OFF TOPIC, and it reached the prompt

    A score threshold cannot separate those: a genuinely relevant Constipation
    chunk scores 0.1703 while an unrelated one scores 0.1251. What DOES separate
    them is the document. The leader wins by roughly 2x every time -- 0.68 vs
    0.34, 0.84 vs 0.43, 0.85 vs 0.45 -- so the top document is unambiguous even
    though its individual chunk scores are not.

    Same reasoning as `knowledge._one_topic_only`, which exists because four
    unrelated notes at similar scores were being handed over "as though they
    answered the question". This is that failure, one service further out.

    Deliberately strict. Grounding rule 13 makes this SUPPORTING material ranked
    below the curated notes, and the graph relationships are the reason to call
    this service at all -- so losing a marginal passage costs little, while an
    off-topic one labelled "Reference documents" costs a wrong answer.
    """
    scored = [
        (p, _first(p, _SCORE_KEYS), _first(p, _SOURCE_KEYS))
        for p in passages
    ]
    ranked = [(p, s, d) for p, s, d in scored if isinstance(s, (int, float)) and d]
    if not ranked:
        # ⚠ THIS USED TO RETURN EVERYTHING, and that failed OPEN. If the vendor
        # stops sending `score`, or sends it as a string, `ranked` is empty and
        # every returned document sailed through - measured, three off-topic
        # notes reached the prompt on a query whose alias claim was corroborated
        # by a fourth. One field change on their side, and the coverage gate is
        # bypassed entirely.
        #
        # With no scores the only signal left is the alias claim, so use it.
        if claimed:
            named = [
                p for p in passages if _first(p, _SOURCE_KEYS) in set(claimed)
            ]
            if named:
                return named
        # `return passages if claimed else []` was still fail-open: when NO
        # passage carries a resolvable source name, the claimed-filter above
        # matches nothing and every document came through on the strength of a
        # claim that nothing in the response corroborated. Measured: four
        # off-topic notes into the prompt on a covered query.
        #
        # No score and no name is no evidence. Refuse.
        print(
            "[graphrag] response carries neither usable scores nor document "
            f"names; dropping {len(passages)} passage(s) rather than guessing"
        )
        return []
    # THE ALIAS INDEX WINS OVER THE SCORE when it has an opinion. Measured:
    #   "constipation treatment"  piles.md 0.5187  >  constipation.md 0.4683
    # The top score is piles; the right note is constipation, and the alias index
    # said so. Picking by score alone lost three of 74 retrieval cases exactly
    # this way. The alias index scores 27/28 as a topic gate against the score's
    # 26/28, and here it is not even close - it is categorical where the score is
    # two similar decimals.
    wanted = {c for c in (claimed or [])}
    if wanted:
        matched = [p for p, _, d in ranked if d in wanted]
        if matched:
            return matched

    best_doc = max(ranked, key=lambda row: row[1])[2]
    return [p for p, _, d in ranked if d == best_doc]


def _first(source: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _read_passages(body: Any) -> list[dict]:
    """Find the passage list in an undocumented response.

    Raises on an unrecognised shape, loudly and with the actual keys. A silent
    empty list would be indistinguishable from "the index had no match", which is
    exactly the confusion to avoid while the schema is still unknown.
    """
    if isinstance(body, list):
        return [p for p in body if isinstance(p, dict)]
    if not isinstance(body, dict):
        raise ValueError(f"expected an object or array, got {type(body).__name__}")

    # Many gateways wrap the payload once.
    inner = body.get("data") if isinstance(body.get("data"), (dict, list)) else None
    if inner is not None:
        return _read_passages(inner)

    for key in _LIST_KEYS:
        value = body.get(key)
        if isinstance(value, list):
            return [p for p in value if isinstance(p, dict)]

    raise ValueError(
        "could not find a passage list. Top-level keys: "
        f"[{', '.join(sorted(body))}]. Add the mapping in "
        "src/retrieval/graphrag.py::_read_passages once a real response is captured."
    )


def english_handle(query: str, collection: str) -> str:
    """Prepend an English term to a Hinglish query, free of charge.

    The vendor calls the index "English-tuned"; this product is Hinglish-first,
    and `config.py` records why that matters -- an English-only embedder scored
    "neend nahi aati" below threshold and retrieved nothing at all.

    The alias index already resolves a Hinglish query to a note, and note
    filenames are English by convention ("gas-bloating.md"), so the stem is an
    English handle we already possess. No extra LLM call, no translation service,
    and the alias index is already loaded for the local retriever on this turn.

    Returns the query unchanged when nothing is claimed.
    """
    try:
        claimed = match_topics(query, collection=collection)
    except Exception:  # noqa: BLE001 - a cold index must never block retrieval
        return query
    if not claimed:
        return query
    terms = " ".join(Path(name).stem.replace("-", " ") for name in claimed)
    return f"{terms} — {query}" if terms else query


# Health signal for the sole remaining grounding source.
#
# Every failure mode of this retriever - timeout, 401, 5xx, DNS, an unrecognised
# response shape - produces the identical `RetrievalResult(chunks=())` and an
# HTTP 200 to the user. Before the cutover that meant a slightly thinner answer,
# because local Chroma still answered. Now it means the turn had NO grounding at
# all, and nothing anywhere says so. These two numbers are what `/health` reports
# so a regression is visible without reading logs.
LAST_SUCCESS_AT: float | None = None
CONSECUTIVE_FAILURES = 0


def health() -> dict:
    """What `/health` publishes about this retriever. No secrets, no URLs."""
    return {
        "last_success_age_s": (
            None if LAST_SUCCESS_AT is None else round(time.monotonic() - LAST_SUCCESS_AT, 1)
        ),
        "consecutive_failures": CONSECUTIVE_FAILURES,
    }


def _stamp_success() -> None:
    """Record a completed call.

    Stamped only AFTER a body has been read, never on a 200 alone. A blank or
    rotated key used to read as perfect health forever because the failure
    happened later than the stamp.
    """
    global LAST_SUCCESS_AT, CONSECUTIVE_FAILURES
    LAST_SUCCESS_AT = time.monotonic()
    CONSECUTIVE_FAILURES = 0


def _stamp_failure(what: str, error: object) -> None:
    """Count and announce a failed call, so an outage cannot be silent."""
    global CONSECUTIVE_FAILURES
    CONSECUTIVE_FAILURES += 1
    print(f"[graphrag] {what} failed ({CONSECUTIVE_FAILURES} in a row): {error}")


def _post_search(
    query: str,
    k: int | None = None,
    document_ids: Sequence[str] | None = None,
    project_id: str | None = None,
) -> dict:
    """POST /v1/search. Blocking; the caller runs it off the event loop.

    Returns the WHOLE body, not just the passages, because the graph lives
    alongside them in `entities` and `edges` and both are needed together -- an
    edge only names entity ids, so it is meaningless without the entity list
    from the same response.

    Shared by the retriever and by the document-id lookup below, so there is one
    place that knows the URL, the credential and the TLS rule.
    """
    import httpx

    base = (config.GRAPHRAG_BASE_URL or "").rstrip("/")
    # Unconfigured used to return {} quietly, which fell through to the success
    # stamp -- so a rotated key on the SOLE grounding source read as perfect
    # health forever. It is an error now, and it is counted.
    if not base or not config.GRAPHRAG_API_KEY:
        raise RuntimeError("GraphRAG is not configured (base url or api key is empty)")

    body: dict[str, Any] = {"query": query, "k": k or config.GRAPHRAG_TOP_K}
    if project_id:
        body["project_id"] = project_id
    if document_ids:
        body["document_ids"] = list(document_ids)

    response = httpx.post(
        f"{base}/v1/search",
        headers={
            "Authorization": f"Bearer {config.GRAPHRAG_API_KEY}",
            "content-type": "application/json",
        },
        json=body,
        # NEVER `verify=False`. The vendor doc is explicit: it leaves the
        # connection encrypted but UNAUTHENTICATED, letting anyone on the
        # network read the API key in transit. An empty bundle falls back to the
        # system trust store, which fails closed on an untrusted certificate.
        verify=config.GRAPHRAG_CA_BUNDLE or True,
        timeout=min(config.RETRIEVAL_TIMEOUT_S, config.GRAPHRAG_TIMEOUT_S),
    )
    response.raise_for_status()
    parsed = response.json()
    return parsed if isinstance(parsed, dict) else {"chunks": parsed}


# ---------------------------------------------------------------------------
# DOCUMENT SELECTION
#
# `document_ids` takes the GRAPH document id (`doc:<uuid>`), which is a
# different id space from the PostgreSQL id that
# GET /v1/projects/{id}/documents returns. The vendor's reference is explicit
# that the two cannot be joined, and there is no endpoint that maps between
# them -- so the only way to learn a note's graph id is to see it on a chunk.
#
# Hence: probe with the note's own name, read the id off whatever comes back,
# and remember it. A probe usually names four or five other notes at the same
# time, so the map fills up quickly on its own.
# ---------------------------------------------------------------------------

_DOCUMENT_IDS: dict[str, str] = {}


def _harvest_ids(body: dict) -> None:
    """Record every filename -> graph document id pair a response mentions."""
    for chunk in body.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        filename, document_id = chunk.get("filename"), chunk.get("document_id")
        if filename and document_id:
            _DOCUMENT_IDS.setdefault(filename, document_id)


def document_id_for(filename: str) -> str | None:
    """The graph document id for a note, looked up once and cached.

    The probe is the filename with its separators opened out -- "gas-bloating"
    rather than "gas-bloating.md" -- because that is what the note is about and
    it is the one string guaranteed to exist for every note, front matter or
    not.
    """
    if filename in _DOCUMENT_IDS:
        return _DOCUMENT_IDS[filename]
    probe = Path(filename).stem.replace("-", " ").replace("_", " ")
    try:
        _harvest_ids(_post_search(probe, k=8))
        _stamp_success()
    except Exception as error:
        _stamp_failure("document id lookup", error)
        return None
    return _DOCUMENT_IDS.get(filename)


def pick_document(query: str, sticky: str | None = None) -> tuple[str | None, str | None]:
    """Choose the ONE note this turn should be answered from.

    ⚠ NOT CALLED IN PRODUCTION RIGHT NOW. `consult/graph.py` stopped sending
    `document_ids` so that the vendor's corpus is the live one - add a note
    there and it answers from it, delete one and it stops, with nothing to
    deploy here. The docstring on `_plan_from_graphrag` records what that costs.

    Kept, not deleted, because it is exactly what gets switched back on if the
    unscoped answers turn out to mix notes too badly to live with. Its tests
    still run, so it will still work when it is wanted.

    Returns (filename, graph document id); either may be None.

    Order, and the reason for it:

    1. THE CONVERSATION'S ESTABLISHED TOPIC. A follow-up like "aur batao"
       matches no alias at all, and asking the service cold returns an unrelated
       menu -- measured, it offered thyroid, back pain and low mood to someone
       three turns into a gas consultation. The topic is sticky until the user
       plainly changes it.
    2. THE ALIAS INDEX, which is author-written and categorical. Measured over
       74 real queries it names the right note 73 times; the service on its own
       manages 48.
    3. THE SERVICE'S OWN TOP DOCUMENT, but only above GRAPHRAG_MIN_RELEVANCE.
       Unfiltered, this step is dangerous rather than helpful: the service
       always names something, so "car ka engine kharab hai" picked
       joint-pain.md and "stock market kaisa hai" picked migraine-headache.md.
       Scoping an answer to those would turn a correct refusal into a confident
       reply about the wrong organ.
    4. Nothing -- and then the caller sends no `document_ids` at all.

    WHY A CONSERVATIVE FLOOR IS THE RIGHT TRADE HERE. Measured on this corpus:

        covered   painful periods every month   period-pain.md      0.3675
        covered   sugar control kaise kare      diabetes.md         0.7295
        covered   skin par daane nikal rahe     acne.md             0.7602
        uncovered naak se khoon aata hai        blood-pressure.md   0.6005
        uncovered mujhe kaan me dard hai        back-pain.md        0.1936
        uncovered car ka engine kharab hai      joint-pain.md       0.0526
        vague     aur batao                     low-mood.md         0.0932

    The two distributions overlap -- 0.3675 is covered and 0.6005 is not -- so
    no threshold separates them cleanly, which is why the alias index runs
    first and is allowed to bypass this floor entirely. For the residue, 0.65
    rejects every uncovered query above, and the price is that "painful periods"
    goes unscoped.

    Unscoped is not a failure: it is exactly what happens today, and the
    service's own grounding instruction still refuses off-topic questions
    ("car ka engine kharab hai" -> "This is not covered in the documents").
    So the worst case of a floor set too high is NO IMPROVEMENT, while the worst
    case of one set too low is a confident answer from the wrong note. Fail
    towards today's behaviour.
    """
    if sticky:
        document_id = document_id_for(sticky)
        if document_id:
            return sticky, document_id

    claimed = match_topics(query, collection=DEFAULT_COLLECTION_NAME)
    if claimed:
        document_id = document_id_for(claimed[0])
        if document_id:
            return claimed[0], document_id

    try:
        body = _post_search(query)
        _harvest_ids(body)
        _stamp_success()
    except Exception as error:
        _stamp_failure("document pick", error)
        return None, None

    passages = _read_passages(body)
    best_score = max(
        (s for s in (_first(p, _SCORE_KEYS) for p in passages) if isinstance(s, (int, float))),
        default=0.0,
    )
    if best_score < config.GRAPHRAG_MIN_RELEVANCE:
        return None, None

    for passage in _top_document_only(passages, claimed):
        filename = _first(passage, _SOURCE_KEYS)
        if filename and filename in _DOCUMENT_IDS:
            return filename, _DOCUMENT_IDS[filename]
    return None, None


# ---------------------------------------------------------------------------
# ANSWER GENERATION
#
# From the 2026-08-25 deployment the vendor also writes the reply, via
# /v1/answer and /v1/answer/stream. We use the streaming one: server.py already
# emits SSE token frames and the browser already reads them, so nothing the
# frontend does has to change.
#
# `document_ids` IS NOT OPTIONAL IN PRACTICE. Without it the model is handed
# passages from several notes and blends them into one confident answer. Live,
# "gas aur bloating ke baare mein aur batao" cited back-pain.md for "naram
# gadda / AC seedha kamar par ... yeh sab gas ko badha sakte hain" - a soft
# mattress presented as a cause of gas. Scoped to the one note, that stops, the
# citations resolve, and the reply gets shorter and twice as fast.
# ---------------------------------------------------------------------------

# The vendor validates 1-2000 and returns 422 outside it. Truncate rather than
# let a long intake turn the whole call into an error.
MAX_QUERY_CHARS = 2000

# Citation markers as the model actually emits them. Three shapes were seen on
# one deployment: `[chunk:doc:<uuid>:N]`, `[chunk:<uuid>:N]` (missing `doc:` -
# the vendor's own validator drops these) and `[doc:<uuid>:N]`. Corrupted uuids
# appear too: `1b26bd74-fd01-4e4d-a869d-...` carries an extra character.
#
# So this MATCHES LOOSELY AND DELETES. It never parses one. Provenance comes
# from the `citations` array, which the vendor validates; the inline markers are
# display noise and must not reach a reader.
# The trailing `:N` is OPTIONAL, and requiring it was a real leak. Scoped to one
# document the model writes `[chunk:doc:<uuid>:3]`; unscoped it cites whole
# documents and writes `[chunk:<uuid>]` with no chunk index at all. The pattern
# demanded the index, so the moment `document_ids` was dropped every uuid went
# straight through to the reader. Caught by test_plan_live, not by reasoning.
# THE BRACKETS ARE OPTIONAL TOO. A weaker model writes the identifier bare -
# `chunk:doc:<uuid>` with nothing around it, or in parentheses - and a
# bracket-only pattern walks straight past it. Seen live the moment the free
# models moved to the head of MODEL_CHAIN.
#
# The bare form REQUIRES an explicit `chunk:` or `doc:` prefix, so this can
# never swallow an ordinary long hex string that happens to sit in the prose.
# `chunk_id:` and `document_id:` are in here because the vendor's own response
# fields are named that, so the model has seen them and does reproduce them. A
# test caught that shape slipping past a pattern that only knew `chunk:`.
# Whitespace after the colon is allowed for the same reason.
_ID_PREFIX = r"(?:chunk(?:_id)?|doc(?:ument)?(?:_id)?)\s*:\s*"
_UUIDISH = r"[0-9a-fA-F][0-9a-fA-F-]{7,}(?::\d+)?"
_CITATION_MARKER = re.compile(
    r"[ \t]*(?:"
    # Bracketed, with an id. `[chunk:doc:<uuid>:3]` and friends.
    rf"[\[(]\s*(?:{_ID_PREFIX})?(?:{_ID_PREFIX})?{_UUIDISH}\s*[\])]"
    # Bracketed, with the prefix but NO id at all - the model writes a bare
    # `[chunk:]` when it means to cite and has nothing to cite. Found in
    # production by the residue detector below, on its first day. The prefix is
    # required here precisely so `[see below]` is not swallowed with it.
    rf"|[\[(]\s*{_ID_PREFIX}\s*[\])]"
    # Unbracketed. Always needs a prefix, so ordinary prose is safe.
    rf"|{_ID_PREFIX}(?:{_ID_PREFIX})?{_UUIDISH}"
    r")"
)
# Deleting " [ref]." leaves " ." behind.
_ORPHAN_SPACE = re.compile(r"[ \t]+([.,;:!?।])")

# How far past a `[` the streaming reader will wait for its `]` before deciding
# this was ordinary prose. The longest real marker is `[chunk:doc:` + a uuid +
# `:N]`, about 55 characters; 80 leaves room for the corrupted uuids the model
# emits without holding a bracketed aside back for a noticeable time.
_MAX_MARKER_CHARS = 80


# Anything that still looks like an identifier AFTER stripping. This is a
# detector, not a second stripper: it exists so a shape we have not seen yet
# announces itself in the log instead of appearing on someone's screen.
#
# Three shapes have already had to be learned from live output rather than
# reasoning - bracketed with a chunk index, bracketed without one, and bare -
# and each was found by chance. Sampling production to catch the next one is
# slow and mostly misses, so the code reports it itself.
_RESIDUE = re.compile(r"(?:chunk(?:_id)?|doc(?:ument)?(?:_id)?)\s*:\s*\S{0,48}")


def strip_citation_markers(text: str) -> str:
    """Remove inline citation markers, so no uuid is ever shown to a user."""
    cleaned = _ORPHAN_SPACE.sub(r"\1", _CITATION_MARKER.sub("", text or ""))

    leftover = _RESIDUE.search(cleaned)
    if leftover:
        # The matched token only, never the prose around it - that prose is
        # somebody's symptoms. This is enough to write the next pattern from.
        print(
            "[graphrag] CITATION SHAPE NOT STRIPPED: "
            f"{leftover.group(0)!r} - add it to _CITATION_MARKER"
        )
    return cleaned


def _answer_request(
    query: str, document_ids: Sequence[str] | None, k: int | None
) -> tuple[str, dict, dict]:
    """(base_url, headers, body) for an answer call, or raise if unconfigured.

    Unconfigured is an error and it is counted, not a quiet empty result: this
    is the only thing that writes the reply now, so a missing key means the
    product has nothing to say and somebody must be told.
    """
    base = (config.GRAPHRAG_BASE_URL or "").rstrip("/")
    if not base or not config.GRAPHRAG_API_KEY:
        raise RuntimeError("GraphRAG is not configured (base url or api key is empty)")

    body: dict[str, Any] = {
        "query": (query or "").strip()[:MAX_QUERY_CHARS],
        "k": k or config.GRAPHRAG_TOP_K,
    }
    if document_ids:
        body["document_ids"] = list(document_ids)
    return base, {
        "Authorization": f"Bearer {config.GRAPHRAG_API_KEY}",
        "content-type": "application/json",
    }, body


def answer(
    query: str, document_ids: Sequence[str] | None = None, k: int | None = None
) -> dict:
    """Blocking. POST /v1/answer -> {answer, citations, graph_used, ...}.

    The non-streaming sibling, kept for tests and for any caller that cannot
    stream. `answer` comes back with markers already stripped.
    """
    import httpx

    base, headers, body = _answer_request(query, document_ids, k)
    try:
        response = httpx.post(
            f"{base}/v1/answer",
            headers=headers,
            json=body,
            # NEVER `verify=False`. An empty bundle falls back to the system
            # trust store, which fails closed on an untrusted certificate.
            verify=config.GRAPHRAG_CA_BUNDLE or True,
            timeout=config.GRAPHRAG_ANSWER_TIMEOUT_S,
        )
        response.raise_for_status()
        parsed = response.json()
    except Exception as error:
        _stamp_failure("answer", error)
        raise

    _stamp_success()
    if not isinstance(parsed, dict):
        return {"answer": "", "citations": []}
    parsed["answer"] = strip_citation_markers(parsed.get("answer") or "")
    return parsed


def answer_stream(
    query: str, document_ids: Sequence[str] | None = None, k: int | None = None
) -> Iterator[str]:
    """Blocking generator. Yields pieces of the reply as the model writes them.

    The caller runs it off the event loop, exactly as `_search` is run.

    Frames are `data: {"t": "<piece>"}` and the stream ends with a literal
    `data: [DONE]`. The piece is JSON-encoded by the vendor precisely so a
    newline or the text "[DONE]" inside it cannot break the framing, so it is
    decoded rather than pattern-matched.

    MARKERS CANNOT BE STRIPPED PER FRAME. A first attempt did exactly that and
    the uuids came straight through: 2145 characters arrived as 729 frames, so
    roughly three characters each, and every marker was split across several of
    them. Nothing matched, and `[chunk:doc:<uuid>:3]` reached the reader.

    So this holds back a tail instead. Once a `[` appears with no `]` after it,
    everything from that `[` is buffered until the bracket closes - or until the
    run is longer than any real marker, which means it was ordinary prose and is
    released. Whitespace immediately before the `[` is held with it, so removing
    " [ref]" does not leave a double space behind.
    """
    import httpx

    base, headers, body = _answer_request(query, document_ids, k)
    seen_done = False
    buffer = ""

    def _flush(text: str) -> tuple[str, str]:
        """Split `text` into (safe to emit now, must be held back)."""
        opened, closed = text.rfind("["), text.rfind("]")
        if opened > closed and len(text) - opened <= _MAX_MARKER_CHARS:
            # A marker may be forming. Hold it, and the whitespace in front of
            # it, so removing " [ref]" does not leave the space behind.
            held = opened
            while held > 0 and text[held - 1] in " \t":
                held -= 1
            return text[:held], text[held:]
        # No bracket pending - but trailing whitespace might be the space BEFORE
        # a marker that has not arrived yet. Emitting it now is what produced a
        # double space around every removed marker, because by the time the `[`
        # showed up its leading space was already gone down the wire.
        safe = text.rstrip(" \t")
        return safe, text[len(safe) :]

    try:
        with httpx.stream(
            "POST",
            f"{base}/v1/answer/stream",
            headers=headers,
            json=body,
            verify=config.GRAPHRAG_CA_BUNDLE or True,
            timeout=config.GRAPHRAG_ANSWER_TIMEOUT_S,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    seen_done = True
                    break
                try:
                    piece = json.loads(payload).get("t", "")
                except Exception:
                    # One unreadable frame is not an outage. Skipping it loses a
                    # few characters; aborting loses the whole consultation.
                    continue
                if not piece:
                    continue
                buffer += piece
                ready, buffer = _flush(buffer)
                if ready:
                    cleaned = strip_citation_markers(ready)
                    if cleaned:
                        yield cleaned
    except Exception as error:
        _stamp_failure("answer/stream", error)
        raise

    if buffer:
        # Whatever is still held back was never a marker, or the stream stopped
        # mid-one. Strip and release it either way; dropping it would silently
        # truncate the reply.
        cleaned = strip_citation_markers(buffer)
        if cleaned:
            yield cleaned

    if not seen_done:
        # The connection ended without [DONE], so the reply is truncated. Say so
        # rather than hand back half an answer that reads as complete - a plan
        # cut off before "When To See A Doctor" is the dangerous half to lose.
        _stamp_failure("answer/stream", "stream ended without [DONE]")
        raise RuntimeError("GraphRAG stream ended before the answer was complete")

    _stamp_success()


class GraphRagRetriever:
    name = "graphrag"
    # Becomes the prompt heading. Named for what it IS to the reader, not for the
    # vendor: "Reference documents" says how much authority to give it.
    section = "Reference documents"
    # Between the user's own uploaded reports (40) and the shared curated notes
    # (50). External material should sit below a document the user gave us and
    # above nothing. `order` affects prompt POSITION only, never ranking.
    order = 45
    enabled = False

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def _search(self, query: str, project_id: str) -> dict:
        """Blocking HTTP. The caller runs it off the event loop.

        Same shape as `retrieval/memory.py::_fetch`, which already does exactly
        this against Convex.

        Returns the WHOLE body, not just the passages, because the graph lives
        alongside them in `entities` and `edges` and both are needed together --
        an edge only names entity ids, so it is meaningless without the entity
        list from the same response.

        The request itself lives in `_post_search`, shared with the document-id
        lookup. The empty-project-id guard stays HERE rather than moving with
        it: the vendor ignores `project_id` on this endpoint, so it buys no
        isolation, but a blank one still means this deployment is misconfigured
        and the retriever should go dark rather than call out with a bare scope.
        """
        if not project_id:
            raise RuntimeError("GraphRAG is not configured (project id is empty)")
        body = _post_search(query, project_id=project_id)
        _harvest_ids(body)
        return body

    async def retrieve(self, ctx: RetrievalContext) -> RetrievalResult:
        # Per-bot scope on the remote index. See the module docstring.
        project_id = config.GRAPHRAG_PROJECT_ID
        if not project_id:
            # Loudly, not silently. This is now the ONLY grounding source, so an
            # unconfigured id means every answer this turn is ungrounded.
            print("[graphrag] no project id configured; retrieving nothing")
            return RetrievalResult(section=self.section, chunks=())

        # Both of these touch the local alias index, which on a cold or broken
        # Chroma can block for a long time. They were running synchronously on
        # the event loop, ABOVE the try/except and outside every timeout, so a
        # stalled store took the whole server down rather than one retrieval.
        # Off the loop, inside the guarded section, like the HTTP call.
        def _topic_lookup() -> tuple[list[str], str]:
            return (
                match_topics(ctx.query, collection=DEFAULT_COLLECTION_NAME),
                english_handle(ctx.query, DEFAULT_COLLECTION_NAME),
            )

        # `pipeline._safe_retrieve` already absorbs timeouts and exceptions, so a
        # wedged or broken service degrades the answer instead of failing the
        # consultation. Caught here as well so the reason is logged with this
        # retriever's name attached.
        try:
            claimed, query = await asyncio.to_thread(_topic_lookup)
            body = await asyncio.to_thread(self._search, query, project_id)
            # Narrowed to the best-scoring document. This service applies no
            # relevance floor of its own, so without this an off-topic passage
            # scoring 0.1251 reached the prompt labelled "Reference documents".
            # Parse FIRST, then stamp. Resetting the counter before parsing meant
            # a vendor schema change - HTTP 200, unreadable body - reset it on
            # every turn, so it could never climb past 1. Measured: six
            # consecutive ungrounded turns reported as one failure and a
            # zero-second-old success. Any alert on >= 3 would never fire.
            passages = _top_document_only(_read_passages(body), claimed) if body else []

            # Stamped here: the round trip returned something we could read. NOT
            # after the coverage gate - the gate returning empty is the system
            # working, and counting that would age the timestamp on ordinary
            # off-topic traffic and hide a real outage behind the noise.
            global LAST_SUCCESS_AT, CONSECUTIVE_FAILURES
            LAST_SUCCESS_AT = time.monotonic()
            CONSECUTIVE_FAILURES = 0

            # THE COVERAGE GATE. This service never returns empty - an off-topic
            # question comes back with its nearest neighbours, and downstream
            # that is indistinguishable from a real answer. With the local
            # retriever off, letting those through means every uncovered
            # question gets a confident plan built on unrelated passages, and
            # the honest-refusal branch can never fire.
            best = max(
                (s for s in (_first(p, _SCORE_KEYS) for p in passages)
                 if isinstance(s, (int, float))),
                default=0.0,
            )
            # ⚠ THE CLAIM MUST BE CORROBORATED BY THE RESPONSE.
            #
            # Gating on `claimed` alone failed OPEN. `claimed` is computed from
            # the QUERY and says nothing about what came back, so for any query
            # the alias index recognises - the common case for real users - the
            # score floor became a no-op. Alias claims gas-bloating, the service
            # returns joint-pain at 0.10, the chunk sails through prefixed
            # `graphrag:`, `knowledge_for_prompt` calls the turn grounded, and
            # rule 13 tells the model that off-topic passage is its FIRST source.
            # Exactly the failure this gate was written to stop, through the
            # other arm.
            #
            # So coverage means: the alias index named a note AND that note is
            # what came back. Otherwise the score has to carry it alone.
            kept_docs = {d for d in (_first(p, _SOURCE_KEYS) for p in passages) if d}
            corroborated = bool(kept_docs & set(claimed or ()))
            if not corroborated and best < config.GRAPHRAG_MIN_RELEVANCE:
                print(
                    f"[graphrag] not covered: {ctx.query[:60]!r} "
                    f"(claimed={claimed or []}, returned={sorted(kept_docs)}, "
                    f"best {best:.4f} < {config.GRAPHRAG_MIN_RELEVANCE})"
                )
                return RetrievalResult(section=self.section, chunks=())
        except Exception as error:  # noqa: BLE001
            CONSECUTIVE_FAILURES += 1
            print(
                f"[graphrag] search failed ({CONSECUTIVE_FAILURES} in a row): {error}. "
                "This turn has NO Ayurveda grounding."
            )
            return RetrievalResult(section=self.section, chunks=())



        chunks = []

        # The graph, first, as one chunk. This is the reason to use this service
        # over the local retriever at all: the notes describe conditions, the
        # graph states relationships between them. Put ahead of the passages so
        # it survives `dedupe`'s limit rather than being crowded out by prose.
        # Relevance is judged against what this turn is actually about: the
        # user's own words plus the passages the service just returned.
        relationships = _read_relationships(
            body,
            context=" ".join(
                [ctx.query, ctx.problem]
                + [str(_first(p, _TEXT_KEYS) or "") for p in passages]
            ),
        )
        if relationships:
            chunks.append(
                Chunk(
                    text="Known relationships:\n" + "\n".join(relationships),
                    source="graphrag:graph",
                    score=None,
                    metadata={"project_id": project_id, "edges": len(relationships)},
                )
            )
        for passage in passages:
            text = _first(passage, _TEXT_KEYS)
            if not isinstance(text, str) or not text.strip():
                continue
            source = _first(passage, _SOURCE_KEYS) or "document"
            score = _first(passage, _SCORE_KEYS)
            chunks.append(
                Chunk(
                    text=text.strip(),
                    # Namespaced like every other source, so `answer-sources.tsx`
                    # groups it without a schema change.
                    source=f"graphrag:{source}",
                    score=float(score) if isinstance(score, (int, float)) else None,
                    metadata={"project_id": project_id},
                )
            )

        return RetrievalResult(
            section=self.section, chunks=dedupe(chunks, limit=config.GRAPHRAG_TOP_K)
        )
