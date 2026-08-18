"""
debug.py
--------
Retrieval introspection for developers. This is the answer to "why did this
Hinglish question get the wrong note?", which is otherwise invisible: the prompt
labels whatever comes back as trusted knowledge, so a wrong chunk produces a
confident, well-written, wrong answer with nothing in the logs to show for it.

WHAT IT EXPOSES
The whole retrieval path for one query, in the order it actually runs:

    raw query
      -> normalised tokens          (what the alias index actually sees)
      -> embedding model in use
      -> alias-index claim          (knowledge.match_topics)
      -> every scored candidate     (INCLUDING the ones below the threshold)
      -> what survived
      -> the assembled prompt block

The rejected candidates are the important part. Knowing that `insomnia.md` scored
0.514 against a 0.52 floor is a completely different bug from it not being
retrieved at all, and only one of those is fixed by tuning the threshold.

ACCESS
Never exposed to an ordinary user. The route in `server.py` is guarded by the
service key, exactly like `/extract`, so there is no request a browser can make
that turns this on. `config.DEBUG_RAG` gates it a second time.

PRIVACY
Returns only what the caller passed plus corpus content that is already public to
the app. It never reads a user's documents unless a `user_id` is supplied by an
already-authenticated caller, and it never returns tokens, keys or secrets.
"""

from __future__ import annotations

import asyncio

import config
from src.bots import BotConfig, get_bot
from src.knowledge import (
    DEFAULT_COLLECTION_NAME,
    _tokens,
    match_topics,
    search_knowledge_scored,
)
from src.retrieval.base import RetrievalContext
from src.retrieval.knowledge import KnowledgeRetriever
from src.retrieval.pipeline import RetrievalPipeline
from src.retrieval.registry import get_pipeline


def _preview(text: str, limit: int = 240) -> str:
    """First `limit` characters, whitespace-collapsed, for a readable dump."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def retrieval_trace(
    query: str, user_id: str | None = None, collection: str | None = None
) -> dict:
    """Full retrieval trace for one query. Blocking — call it off the event loop.

    Deliberately re-runs the search rather than instrumenting the live path: a
    debug flag threaded through the request path is a permanent complication and
    a permanent risk of leaking into a real response. Re-running costs one extra
    embed on a developer-only route.

    ⚠ `kept` COMES FROM THE REAL RETRIEVER, not from a threshold applied here.
    This used to re-implement the filter as `score >= MIN_RELEVANCE`, which is
    only what `_search` does when the alias index claims NOTHING. On a claim it
    returns every scored chunk from the claimed notes and skips the floor - so
    this route reported `kept_count: 0` for "mujhe gas ho rahi hai" while live
    retrieval was serving four chunks from gas-bloating.md. That is the exact
    opposite of the truth, on the single most common query in the product, from
    the one tool anybody would reach for to explain a bad answer. It sent this
    author chasing a retrieval bug that did not exist.

    `collection` matters for the same reason `_search` takes it: without it every
    trace describes the default bot's corpus whatever bot was asked about.
    """
    tokens = [t for t in _tokens(query) if len(t) >= 2]
    name = collection or DEFAULT_COLLECTION_NAME
    claimed = match_topics(query, collection=name)

    # Unfiltered, so the rejected candidates and their scores stay visible. This
    # is the only view that distinguishes "scored just under the floor" from
    # "never retrieved", and it is why the raw list is still fetched separately.
    scored = search_knowledge_scored(query, config.VECTOR_FETCH_K, collection=name)

    # What the consultation would ACTUALLY have received, alias bypass and
    # `_one_topic_only` included, by calling the retriever's own search.
    _, real_kept = KnowledgeRetriever(enabled=True)._search(query, name)
    kept_keys = {(d.metadata.get("source", "?"), d.page_content) for d, _ in real_kept}

    candidates = [
        {
            "source": doc.metadata.get("source", "?"),
            "score": round(score, 4) if score is not None else None,
            "kept": (doc.metadata.get("source", "?"), doc.page_content) in kept_keys,
            "over_floor": score is None or score >= config.MIN_RELEVANCE,
            "topic": doc.metadata.get("topic", ""),
            "text": _preview(doc.page_content),
        }
        for doc, score in scored
    ]

    return {
        "query": query,
        "collection": name,
        "normalised_tokens": tokens,
        "embedding_model": config.EMBEDDING_MODEL,
        "min_relevance": config.MIN_RELEVANCE,
        "fetch_k": config.VECTOR_FETCH_K,
        "top_k": config.VECTOR_TOP_K,
        "reranker_enabled": config.RERANKER_ENABLED,
        # An alias claim BYPASSES the threshold by design (see
        # retrieval/knowledge.py). `kept` already reflects that; `over_floor` on
        # each candidate shows what the score alone would have decided, so the
        # two together say WHY a chunk survived.
        "alias_index_claimed": claimed,
        "threshold_bypassed_by_alias": bool(claimed),
        "candidate_count": len(candidates),
        "kept_count": len(real_kept),
        "candidates": candidates,
        "best_score": max(
            (c["score"] for c in candidates if c["score"] is not None), default=None
        ),
    }


async def pipeline_trace(
    query: str, user_id: str | None = None, bot: BotConfig | None = None
) -> dict:
    """The retrieval trace PLUS what the full pipeline assembled for the prompt.

    `retrieval_trace` explains the knowledge retriever in isolation; this shows
    what every enabled retriever contributed and the exact text the model would
    receive, which is where ordering and section-labelling bugs show up.

    `bot` picks which corpus to describe, and must be the bot the caller asked
    about — a trace of the wrong corpus is worse than no trace, because it looks
    entirely plausible. Validated at the HTTP edge, same as a real consultation.
    """
    bot = bot or get_bot(None)
    trace = await asyncio.to_thread(
        retrieval_trace, query, user_id, bot.knowledge_collection
    )

    ctx = RetrievalContext(query=query, problem=query, user_id=user_id, bot=bot)
    results = await get_pipeline().run(ctx)

    trace["retrievers"] = [
        {
            "section": r.section,
            "chunks": len(r.chunks),
            "sources": [c.source for c in r.chunks],
        }
        for r in results
    ]
    trace["assembled_context"] = RetrievalPipeline.to_prompt_block(results)
    trace["sources"] = RetrievalPipeline.to_sources(results)
    return trace
