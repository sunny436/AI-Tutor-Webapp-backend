"""
retrieval/knowledge.py
----------------------
The one retriever that is live today: vector search over the curated
Ayurveda/Yoga notes in `data/knowledge/`, via ChromaDB and a local
`all-MiniLM-L6-v2` embedding model.

This is the vector-search stage of the target pipeline. It wraps the existing
`src/knowledge.py` rather than replacing it, because the legacy /chat path still
calls `search_knowledge` directly.

TWO WAYS IN, BECAUSE VECTORS ALONE ARE NOT ENOUGH
Retrieval runs the author-written alias index FIRST, and only falls back to pure
vector search when no note claims the topic.

That order is not a preference, it is what the measurements forced. The users
here type romanised Hindi, which the multilingual embedder handles unevenly:
"gas ki problem" found `gas-bloating.md` at 0.59, but "pet phoolna" did not
return that note anywhere in the top 12 — despite "pet phoolna" being listed
verbatim in its aliases. Same for "baal jhad rahe hain" against `hair-fall.md`.
A keyword the author explicitly wrote down must not lose to a similarity score.

Once a note is identified, the vector search still runs — narrowed to that note —
so ranking picks the best SECTION rather than having to find the note at all.

AN HONEST EMPTY RESULT
When no alias matches, a plain top-k search still returns k chunks whatever the
question, so an off-topic question comes back with the least-bad notes labelled
"trusted knowledge" and the model builds its answer around them. Results below
`MIN_RELEVANCE` are therefore dropped, this retriever returns empty, the prompt
says so plainly, and the model answers from general Ayurveda knowledge instead.
"""

from __future__ import annotations

import asyncio

import config
from src.knowledge import match_topics, search_knowledge_scored
from src.retrieval.base import Chunk, RetrievalContext, RetrievalResult
from src.retrieval.pipeline import dedupe

# Read through to config so retrieval can be tuned per deployment without a code
# edit. Names kept for the existing call sites and tests.
FETCH_K = config.VECTOR_FETCH_K
KEEP_K = config.VECTOR_TOP_K

# Measured with BAAI/bge-m3 (cosine, 204 chunks / 29 notes) over the 74 positive
# and 10 negative queries in `tests/retrieval_cases.py`:
#
#   on-topic   min 0.423 | p10 0.515 | median 0.589 | max 0.698
#   off-topic  min 0.333 | median 0.445 | max 0.507
#
# The two ranges OVERLAP, so no threshold is clean and the choice is a trade:
#
#   0.50  93% of positives kept, 1 negative leaks
#   0.52  85% of positives kept, 0 negatives leak
#
# 0.52, because the two errors are not symmetric. A leaked negative gets labelled
# "trusted knowledge" and the model builds a confident answer around a note about
# something else — the failure users actually complain about. A dropped positive
# just means answering from general Ayurveda knowledge, which reads fine.
#
# The 15% of positives this drops are overwhelmingly ones the alias index has
# already claimed by name before the threshold is ever consulted, which is why
# end-to-end recall stays at 1.00 (see tests/test_retrieval.py).
#
# Now sourced from config (env: KNOWLEDGE_MIN_RELEVANCE) rather than read here
# directly, so every retrieval knob has one home. The number above is only valid
# for the embedding model it was measured on — re-measure if that changes.
MIN_RELEVANCE = config.MIN_RELEVANCE


class KnowledgeRetriever:
    name = "knowledge"
    section = "Trusted Ayurveda / Yoga knowledge"
    order = 50
    enabled = True

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def _search(self, query: str) -> tuple[list, list]:
        """Return `(everything scored, what survived)` for one query.

        Blocking on purpose — the caller runs it off the event loop.
        """
        claimed = match_topics(query)
        if claimed:
            # A note's own aliases named this topic. Trust that over the score:
            # the threshold exists to reject questions nothing covers, and this
            # question is demonstrably covered. Ranking now only chooses the
            # section.
            scored = search_knowledge_scored(query, FETCH_K, sources=claimed)
            if scored:
                print(f"[knowledge] topic index matched {', '.join(claimed)}")
                return scored, scored
            # Index and store disagree (a note deleted since ingest) — fall through.

        scored = search_knowledge_scored(query, FETCH_K)
        kept = [(doc, score) for doc, score in scored if score is None or score >= MIN_RELEVANCE]
        if scored and not kept:
            best = max((s for _, s in scored if s is not None), default=None)
            print(
                f"[knowledge] nothing relevant for {query[:60]!r} "
                f"(best score {best}); answering from general knowledge"
            )
        return scored, kept

    async def retrieve(self, ctx: RetrievalContext) -> RetrievalResult:
        # Chroma and sentence-transformers are blocking C/NumPy work, so this has
        # to leave the event loop or it stalls every concurrent request.
        scored, kept = await asyncio.to_thread(self._search, ctx.query)

        chunks = [
            Chunk(
                text=doc.page_content,
                source=f"knowledge:{doc.metadata.get('source', 'notes')}",
                score=score,
                metadata=dict(doc.metadata or {}),
            )
            for doc, score in kept
        ]
        return RetrievalResult(section=self.section, chunks=dedupe(chunks, limit=KEEP_K))
