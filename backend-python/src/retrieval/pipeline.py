"""
retrieval/pipeline.py
---------------------
Runs the retrievers and turns what they found into a prompt block.

Two rules drive the design:

1. **Concurrent execution, ordered assembly.** The stages are independent I/O
   (Chroma on disk today; Convex round-trips tomorrow). Running them in sequence
   would add up their latencies for no benefit, so they run together and the
   *results* are sorted into the specified pipeline order afterwards.

2. **Retrieval must never fail a consultation.** A retriever that raises, or is
   slow, contributes nothing and the answer is still written. Grounding is an
   enhancement; losing it degrades quality, it should never produce an error page.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

import config
from src.retrieval.base import Chunk, RetrievalContext, RetrievalResult, Retriever

# Per-retriever budget, the cap that keeps a slow or wedged source from holding
# up the whole consultation. Retrievers run concurrently below, so this bounds
# the pipeline rather than accumulating across it.
#
# Nothing here is local any more: the Convex retrievers were always network
# calls, and since embeddings moved to OpenRouter so is every Chroma query -
# it embeds the query remotely before it can search. The measurements and the
# incident that set this number are recorded at config.RETRIEVAL_TIMEOUT_S.
DEFAULT_TIMEOUT_S = config.RETRIEVAL_TIMEOUT_S


class RetrievalPipeline:
    def __init__(
        self,
        retrievers: Sequence[Retriever],
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._retrievers = sorted(retrievers, key=lambda r: r.order)
        self._timeout_s = timeout_s

    async def run(self, ctx: RetrievalContext) -> list[RetrievalResult]:
        """Gather from every enabled retriever, in pipeline order."""
        active = [r for r in self._retrievers if r.enabled]
        if not active:
            return []

        gathered = await asyncio.gather(
            *(self._safe_retrieve(r, ctx) for r in active),
            return_exceptions=False,
        )
        # `active` is already order-sorted, and gather preserves input order.
        return [r for r in gathered if not r.is_empty]

    async def _safe_retrieve(
        self, retriever: Retriever, ctx: RetrievalContext
    ) -> RetrievalResult:
        try:
            return await asyncio.wait_for(
                retriever.retrieve(ctx), timeout=self._timeout_s
            )
        except asyncio.TimeoutError:
            print(f"[retrieval] {retriever.name} timed out after {self._timeout_s}s")
        except Exception as error:  # noqa: BLE001 - never fail the consult
            print(f"[retrieval] {retriever.name} failed: {error}")
        return RetrievalResult(section=retriever.section, chunks=())

    # ---- prompt assembly ---------------------------------------------------

    @staticmethod
    def to_prompt_block(results: Sequence[RetrievalResult]) -> str:
        """Render retrieved chunks as labelled prompt sections.

        The `[Note N - from X]` presentation lives here, not inside a retriever —
        a retriever returns data, the pipeline decides how the prompt reads.
        """
        blocks: list[str] = []
        for result in results:
            if result.is_empty:
                continue
            lines = [f"--- {result.section.upper()} ---"]
            for index, chunk in enumerate(result.chunks, start=1):
                lines.append(f"[{index} - from {chunk.source}]\n{chunk.text}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    @staticmethod
    def to_sources(results: Sequence[RetrievalResult]) -> list[dict]:
        """Compact provenance list, safe to return to the client."""
        sources: list[dict] = []
        for result in results:
            for chunk in result.chunks:
                sources.append(
                    {
                        "section": result.section,
                        "source": chunk.source,
                        "score": chunk.score,
                    }
                )
        return sources


def dedupe(chunks: Sequence[Chunk], limit: int | None = None) -> list[Chunk]:
    """Drop chunks whose text repeats, keeping the best-scoring first occurrence.

    Needed because the knowledge store has historically accumulated duplicate
    copies of the same note (see scripts/ingest_knowledge.py), which would
    otherwise spend the whole top-k budget on one passage.
    """
    seen: set[str] = set()
    unique: list[Chunk] = []
    for chunk in chunks:
        key = " ".join(chunk.text.split()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(chunk)
        if limit is not None and len(unique) >= limit:
            break
    return unique
