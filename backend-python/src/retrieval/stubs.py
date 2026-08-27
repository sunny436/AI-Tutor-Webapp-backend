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

import config
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


# Stage 2 (previous conversations) is IMPLEMENTED and has moved to
# `src/retrieval/memory.py` — a working retriever does not belong in a file
# called stubs.py. `registry.py` imports it from there.


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
    # Tunable via REPORT_MIN_RELEVANCE / REPORT_TOP_K.
    MIN_RELEVANCE = config.REPORT_MIN_RELEVANCE
    TOP_K = config.REPORT_TOP_K

    # How many chunks any ONE file may contribute when the question is about the
    # attachments themselves. Two, not one: a single chunk off the top of a
    # report is often just its header, which describes nothing.
    PER_DOCUMENT = 2

    async def retrieve(self, ctx: RetrievalContext) -> RetrievalResult:
        # No verified user, no private data. `user_documents.search` refuses an
        # empty id as well; both checks stay, because this is the failure that
        # would leak one person's medical history to another.
        if not ctx.user_id:
            return RetrievalResult(section=self.section, chunks=())

        import asyncio

        from src import user_documents

        # A question ABOUT the attachments has to reach ALL of them. TOP_K is a
        # global budget, so with several files the highest-scoring one can take
        # every slot and the others are never mentioned - and a subject-less
        # question scores them almost identically anyway (measured 0.322 against
        # 0.288 for two unrelated reports), so which one wins is close to noise.
        # Ask for enough rows that every file can be represented, then even them
        # out below.
        about_documents = bool(ctx.extras.get("document_question"))
        filenames: list[str] = []
        if about_documents:
            try:
                filenames = await asyncio.to_thread(
                    user_documents.list_documents, ctx.user_id
                )
            except Exception:  # noqa: BLE001
                filenames = []
        k = max(self.TOP_K, len(filenames) * self.PER_DOCUMENT) if about_documents else self.TOP_K

        try:
            # Chroma is blocking, and this runs inside the request event loop
            # alongside the other retrievers - inline it would stall them all.
            hits = await asyncio.to_thread(
                user_documents.search, ctx.user_id, ctx.query, k
            )
        except Exception as error:  # noqa: BLE001
            # A broken document index must not take the consultation down: the
            # shared knowledge base can still answer.
            print(f"[uploaded_reports] retrieval failed: {error}")
            return RetrievalResult(section=self.section, chunks=())

        # A question ABOUT the attachment ("what is this pdf about") carries no
        # subject, so it is similar to nothing and every chunk falls under the
        # floor - the model is handed an empty block and truthfully answers that
        # no file was attached. The floor exists to keep an UNRELATED report out
        # of an unrelated answer; when the report IS the question, there is
        # nothing to keep out. Set only by `_retrieve` for that one turn.
        floor = 0.0 if about_documents else self.MIN_RELEVANCE
        kept = [(f, t, s) for f, t, s in hits if s >= floor]

        if about_documents and filenames:
            # Cap each file's share so one long report cannot crowd the others
            # out of the prompt. Order follows the score, so the closest match
            # still leads; the point is only that nothing is missing.
            per_file: dict[str, int] = {}
            evened = []
            for filename, text, score in kept:
                if per_file.get(filename, 0) >= self.PER_DOCUMENT:
                    continue
                per_file[filename] = per_file.get(filename, 0) + 1
                evened.append((filename, text, score))
            kept = evened

        chunks = tuple(
            Chunk(
                text=text,
                source=f"report:{filename}",
                score=score,
                metadata={"filename": filename},
            )
            for filename, text, score in kept
        )
        return RetrievalResult(section=self.section, chunks=chunks)
