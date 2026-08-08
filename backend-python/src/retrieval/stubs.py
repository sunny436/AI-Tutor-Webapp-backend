"""
retrieval/stubs.py
------------------
The four RAG stages that are declared but not yet implemented.

Each one returns an EMPTY result rather than raising. That is deliberate: the
pipeline, prompt assembly and provenance paths all run in production from day
one, so switching a stage on later is a flag flip plus a method body — not an
integration.

To implement one:
  1. set `enabled = True` in `registry.py`
  2. fill in `retrieve()` below, returning `Chunk`s
  3. done — the consultation flow and the client are untouched

All four read server-owned data, so they use `ctx.user_id` / `ctx.session_id` /
`ctx.auth_token` (populated from a verified Convex JWT). They must never accept
this data from the request body.
"""

from __future__ import annotations

from src.retrieval.base import Chunk, RetrievalContext, RetrievalResult


class _Stub:
    """Shared no-op behaviour: declared, ordered, and silent."""

    name = "stub"
    section = "Stub"
    order = 99
    enabled = False

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    async def retrieve(self, ctx: RetrievalContext) -> RetrievalResult:
        return RetrievalResult(section=self.section, chunks=())


class UserHistoryRetriever(_Stub):
    """Stage 1 — the user's own reported history and long-term context.

    TODO: read the user's saved health profile facts (conditions, allergies,
    long-standing habits) from Convex by `ctx.user_id`.
    """

    name = "user_history"
    section = "This user's health history"
    order = 10


class PreviousConversationsRetriever(_Stub):
    """Stage 2 — what this user discussed in earlier consultations.

    TODO: query the Convex `consults` table by `ctx.user_id`, most recent first,
    and summarise. Note transcripts are already stored there by `chats.save`, so
    this is the cheapest stage to enable next.
    """

    name = "previous_conversations"
    section = "Earlier consultations with this user"
    order = 20


class MedicalProfileRetriever(_Stub):
    """Stage 3 — structured medical profile (age, constitution, medication…).

    TODO: needs a `profiles` table in Convex; none exists yet. The intake answers
    collected by `src/consult/` are the natural source to seed it from.
    """

    name = "medical_profile"
    section = "Medical profile"
    order = 30


class UploadedReportsRetriever(_Stub):
    """Stage 4 — text extracted from uploaded lab reports and prescriptions.

    LIVE. `POST /upload` extracts the text (`src/documents.py`) and embeds it
    against the uploader (`src/user_documents.py`); this reads it back.

    `order = 40` puts these chunks above the shared knowledge notes (50) in the
    assembled prompt. That is placement, not ranking — per `registry.py` the
    retrievers run concurrently and `order` only decides where each lands — but
    it is the right placement: what this specific person's report says should be
    in front of the model before the general note about the same complaint.
    """

    name = "uploaded_reports"
    section = "Uploaded medical reports"
    order = 40

    # Reports use different vocabulary from a symptom description - "serum
    # creatinine" against "kamzori lag rahi hai" - so demanding the same
    # similarity as the curated notes would return nothing useful. Lower, but
    # not zero: an unrelated report should still stay out of the prompt.
    MIN_RELEVANCE = 0.30
    TOP_K = 4

    async def retrieve(self, ctx: RetrievalContext) -> RetrievalResult:
        # No verified user, no private data. `user_documents.search` refuses an
        # empty id as well; both checks stay, because this is the failure that
        # would leak one person's medical history to another.
        if not ctx.user_id:
            return RetrievalResult(section=self.section, chunks=())

        import asyncio

        from src import user_documents

        try:
            # Chroma is blocking, and this runs inside the request event loop
            # alongside the other retrievers - inline it would stall them all.
            hits = await asyncio.to_thread(
                user_documents.search, ctx.user_id, ctx.query, self.TOP_K
            )
        except Exception as error:  # noqa: BLE001
            # A broken document index must not take the consultation down: the
            # shared knowledge base can still answer.
            print(f"[uploaded_reports] retrieval failed: {error}")
            return RetrievalResult(section=self.section, chunks=())

        chunks = tuple(
            Chunk(
                text=text,
                source=f"report:{filename}",
                score=score,
                metadata={"filename": filename},
            )
            for filename, text, score in hits
            if score >= self.MIN_RELEVANCE
        )
        return RetrievalResult(section=self.section, chunks=chunks)
