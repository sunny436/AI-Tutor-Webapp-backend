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
from src.knowledge import _tokens, match_topics, search_knowledge_scored
from src.retrieval.base import RetrievalContext
from src.retrieval.pipeline import RetrievalPipeline
from src.retrieval.registry import get_pipeline


def _preview(text: str, limit: int = 240) -> str:
    """First `limit` characters, whitespace-collapsed, for a readable dump."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def retrieval_trace(query: str, user_id: str | None = None) -> dict:
    """Full retrieval trace for one query. Blocking — call it off the event loop.

    Deliberately re-runs the search rather than instrumenting the live path: a
    debug flag threaded through the request path is a permanent complication and
    a permanent risk of leaking into a real response. Re-running costs one extra
    embed on a developer-only route.
    """
    tokens = [t for t in _tokens(query) if len(t) >= 2]
    claimed = match_topics(query)

    # Unfiltered, so the rejected candidates and their scores are visible. This
    # is the only view that distinguishes "scored just under the floor" from
    # "never retrieved".
    scored = search_knowledge_scored(query, config.VECTOR_FETCH_K)
    candidates = [
        {
            "source": doc.metadata.get("source", "?"),
            "score": round(score, 4) if score is not None else None,
            "kept": score is None or score >= config.MIN_RELEVANCE,
            "topic": doc.metadata.get("topic", ""),
            "text": _preview(doc.page_content),
        }
        for doc, score in scored
    ]
    kept = [c for c in candidates if c["kept"]]

    return {
        "query": query,
        "normalised_tokens": tokens,
        "embedding_model": config.EMBEDDING_MODEL,
        "min_relevance": config.MIN_RELEVANCE,
        "fetch_k": config.VECTOR_FETCH_K,
        "top_k": config.VECTOR_TOP_K,
        "reranker_enabled": config.RERANKER_ENABLED,
        # An alias claim BYPASSES the threshold by design (see
        # retrieval/knowledge.py), so a surprising result is often explained here
        # rather than by the scores.
        "alias_index_claimed": claimed,
        "candidate_count": len(candidates),
        "kept_count": len(kept),
        "candidates": candidates,
        "best_score": max(
            (c["score"] for c in candidates if c["score"] is not None), default=None
        ),
    }


async def pipeline_trace(query: str, user_id: str | None = None) -> dict:
    """The retrieval trace PLUS what the full pipeline assembled for the prompt.

    `retrieval_trace` explains the knowledge retriever in isolation; this shows
    what every enabled retriever contributed and the exact text the model would
    receive, which is where ordering and section-labelling bugs show up.
    """
    trace = await asyncio.to_thread(retrieval_trace, query, user_id)

    ctx = RetrievalContext(query=query, problem=query, user_id=user_id)
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
