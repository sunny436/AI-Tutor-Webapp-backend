"""
retrieval/graphrag.py
---------------------
The external GraphRAG document service, as one more retriever.

SHIPS DORMANT. `config.GRAPHRAG_ENABLED` defaults to 0, so this contributes
nothing until it is switched on. That is deliberate: the service is not reachable
from this machine yet (see BLOCKERS below), and a retriever that cannot be
exercised should not be able to affect a live consultation.

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

BLOCKERS -- both real, both outside this file
1. `graphrag.internal` does not resolve from this machine, and the vendor doc
   forbids the raw IP because the certificate is issued for the name. Fixing it
   needs a DNS record or an Administrator hosts edit.
2. The `/v1/search` RESPONSE BODY IS NOT DOCUMENTED. The brief shows the request
   for search and answer, and a response only for upload. So the field holding
   passage text, the field holding document identity, and whether a score comes
   back at all are all unknown.

`_read_passages` below is therefore written as a TOLERANT READER, not a guess
dressed up as a fact -- the same approach already taken in
`apps/app/src/lib/consult/central.ts` for the same reason. It accepts the shapes
such an API realistically returns and, when it recognises none of them, raises an
error naming the keys it actually received. Filling in the real mapping is then a
glance at that message rather than a debugging session.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import config
from src.knowledge import match_topics
from src.retrieval.base import Chunk, RetrievalContext, RetrievalResult
from src.retrieval.pipeline import dedupe

# Candidate keys, most specific first. Every one of these is a GUESS about an
# undocumented response and is treated as such: nothing here is relied on, and an
# unrecognised shape raises rather than silently returning nothing.
_LIST_KEYS = ("results", "passages", "chunks", "matches", "hits", "documents", "items")
_TEXT_KEYS = ("text", "content", "passage", "chunk", "page_content", "body", "snippet")
_SOURCE_KEYS = ("document_name", "filename", "source", "title", "document_id", "id")
# Deliberately NOT including "distance": distance is INVERTED relative to
# relevance, so reading one as the other would rank the worst passage first.
# An unrecognised score is left as None, which the UI already renders as
# "no score" rather than as zero.
_SCORE_KEYS = ("score", "relevance", "relevance_score", "similarity")


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

    def _search(self, query: str, project_id: str) -> list[dict]:
        """Blocking HTTP. The caller runs it off the event loop.

        Same shape as `retrieval/memory.py::_fetch`, which already does exactly
        this against Convex.
        """
        import httpx

        base = (config.GRAPHRAG_BASE_URL or "").rstrip("/")
        # Unconfigured is not an error -- it means this source is simply off.
        if not base or not config.GRAPHRAG_API_KEY or not project_id:
            return []

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
        return _read_passages(response.json())

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
            passages = await asyncio.to_thread(self._search, query, project_id)
        except Exception as error:  # noqa: BLE001
            print(f"[graphrag] search failed: {error}")
            return RetrievalResult(section=self.section, chunks=())

        chunks = []
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
