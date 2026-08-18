"""
retrieval/graphrag.py
---------------------
The external GraphRAG document service, as one more retriever.

SHIPS DORMANT. `config.GRAPHRAG_ENABLED` defaults to 0, so this contributes
nothing until it is switched on. It is now fully connected and verified against
the live service, so the remaining reasons to leave it off are latency and an
open decision about the graph -- both recorded below.

WHY A RETRIEVER AND NOT A BRANCH IN consult/graph.py
`retrieval/registry.py` states its own contract: adding a knowledge source is one
retriever file plus one line there, and nothing in `src/consult/` changes. This
follows it exactly, so nothing downstream learns that a passage came from a
remote service -- `to_prompt_block` renders it like any other section and
`to_sources` emits a citation for it like any other chunk.

/v1/search, NEVER /v1/answer
The vendor exposes both. `/v1/answer` writes prose with its OWN model, which
would put a second, unaudited LLM into a health product: it has never seen
SYSTEM_RULES, so it does not know that it must not name a medicine (rule 2), must
mirror the user's language (rule 6), or must not claim to be a practitioner
(rule 7). It would also not produce the exact section headings the UI colours on.
So this asks only for passages, and our single existing LLM still writes every
word the user reads.

BOT-SCOPED, LIKE THE LOCAL CORPUS
The project id comes from `ctx.bot.graphrag_project_id`, never from
`config.GRAPHRAG_PROJECT_ID`. Reading the global would have punched a hole
straight through the isolation boundary added with the Bot Manager: every bot
would query the same remote project, so one bot could retrieve another's
documents from the external index -- the same leak, one layer further out.
`config.GRAPHRAG_PROJECT_ID` survives only as the DEFAULT BOT's value inside
`src/bots/registry.py`; nothing on the request path reads it.

VERIFIED AGAINST THE LIVE SERVICE (2026-08-18)
DNS, TLS against the vendor CA with full hostname checking, authentication, and a
real populated response have all been exercised end to end. The shape below is
observed, not guessed. Two things still stand between this and being switched on:

1. LATENCY. Measured on five real calls: 2.43s, 3.72s, 5.59s, 7.28s, 3.07s. The
   per-retriever budget is min(RETRIEVAL_TIMEOUT_S, GRAPHRAG_TIMEOUT_S) = 3.0s,
   so most calls currently time out. Raising it means raising
   RETRIEVAL_TIMEOUT_S, which the pipeline applies to EVERY retriever, so a slow
   GraphRAG would delay every consultation on the site. That is a trade to make
   deliberately, not a number to nudge.

2. THE GRAPH. See the note on `entities` and `edges` below.

`_read_passages` remains a TOLERANT READER even though the shape is now known --
the same approach as `apps/app/src/lib/consult/central.ts`. This is a pilot API
whose response is still documented nowhere, so it accepts the shapes such a
service realistically returns and, when it recognises none, raises an error
naming the keys it actually received rather than returning a quiet empty list.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import config
from src.knowledge import match_topics
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

# ⚠ THE ONLY IDENTIFIER RETURNED IS `document_id`, AND IT IS A UUID.
#
# There is no filename and no title, so a citation reads
# "graphrag:doc:b2522dcf-82d2-4173-821b-3756e91b1cf0" rather than something a
# person could look up. It is kept anyway: it is stable, it is what the vendor's
# delete/retry endpoints take, and it makes a retrieved passage traceable back to
# an upload when debugging. But nothing here should be shown to a reader as-is.
#
# Restoring a human-readable name would mean keeping an id->filename map at upload
# time. Not built, because per-answer citations are not currently displayed.
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


def _top_document_only(passages: list[dict]) -> list[dict]:
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
        # No scores or no document ids to group by -- nothing to reason about, so
        # pass everything through rather than silently dropping the lot.
        return passages
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
        """
        import httpx

        base = (config.GRAPHRAG_BASE_URL or "").rstrip("/")
        # Unconfigured is not an error -- it means this source is simply off.
        if not base or not config.GRAPHRAG_API_KEY or not project_id:
            return {}

        response = httpx.post(
            f"{base}/v1/search",
            headers={
                "Authorization": f"Bearer {config.GRAPHRAG_API_KEY}",
                "content-type": "application/json",
            },
            json={"query": query, "k": config.GRAPHRAG_TOP_K, "project_id": project_id},
            # NEVER `verify=False`. The vendor doc is explicit: it leaves the
            # connection encrypted but UNAUTHENTICATED, letting anyone on the
            # network read the API key in transit. An empty bundle falls back to
            # the system trust store, which is the correct default -- it fails
            # closed on an untrusted cert rather than silently accepting one.
            verify=config.GRAPHRAG_CA_BUNDLE or True,
            timeout=min(config.RETRIEVAL_TIMEOUT_S, config.GRAPHRAG_TIMEOUT_S),
        )
        response.raise_for_status()
        body = response.json()
        return body if isinstance(body, dict) else {"chunks": body}

    async def retrieve(self, ctx: RetrievalContext) -> RetrievalResult:
        # Per-bot scope on the remote index. See the module docstring.
        project_id = ctx.bot.graphrag_project_id
        if not project_id:
            return RetrievalResult(section=self.section, chunks=())

        query = english_handle(ctx.query, ctx.bot.knowledge_collection)

        # `pipeline._safe_retrieve` already absorbs timeouts and exceptions, so a
        # wedged or broken service degrades the answer instead of failing the
        # consultation. Caught here as well so the reason is logged with this
        # retriever's name attached.
        try:
            body = await asyncio.to_thread(self._search, query, project_id)
            # Narrowed to the best-scoring document. This service applies no
            # relevance floor of its own, so without this an off-topic passage
            # scoring 0.1251 reached the prompt labelled "Reference documents".
            passages = _top_document_only(_read_passages(body)) if body else []
        except Exception as error:  # noqa: BLE001
            print(f"[graphrag] search failed: {error}")
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
