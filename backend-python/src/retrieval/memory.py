"""
retrieval/memory.py
-------------------
Long-term memory: what this user discussed in EARLIER consultations.

Stage 2 of the pipeline (order 20), so it lands above the shared Ayurveda notes
in the assembled prompt — what this specific person already told us should reach
the model before a general note about the same complaint.

WHERE THE DATA COMES FROM
Convex has stored every turn in `consults` since day one; nothing could read it
back. This calls the service-key-guarded `/backend/user-memory` route added to
`convex/http.ts`, which runs the `internal` query `memory.recentTurns`.

WHY THE USER ID IS SAFE
`ctx.user_id` is written by `server.py` from a VERIFIED Convex JWT and never from
the request body (see the comment at the RetrievalContext construction in
`consult/graph.py`). The Convex route is `internal` behind a service key, so
there is no path by which a browser can ask for somebody else's id. Both halves
matter: either one alone would leave a cross-tenant hole.

MEMORY IS CONTEXT, NOT TRUTH
These chunks are labelled as earlier conversation, and prompt rule 11 tells the
model that the current message wins when the two disagree. Somebody saying "that
problem is gone now" must not be argued with by their own history.
"""

from __future__ import annotations

import asyncio

import config
from src.retrieval.base import Chunk, RetrievalContext, RetrievalResult

# Keep the prompt share small. This is background, not the question being asked,
# and every line here competes with the curated notes for the model's attention.
MAX_TURNS = 8
MAX_CHARS = 600


class PreviousConversationsRetriever:
    name = "previous_conversations"
    section = "Earlier consultations with this user"
    order = 20
    enabled = True

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def _fetch(self, user_id: str, session_id: str | None) -> list[dict]:
        """Blocking HTTP to Convex. The caller runs it off the event loop."""
        import httpx

        base = (config.CONVEX_SITE_URL or "").rstrip("/")
        if not base or not config.SERVICE_KEY:
            # Unconfigured is not an error — it means memory is simply off.
            return []

        response = httpx.post(
            f"{base}/backend/user-memory",
            headers={
                "x-service-key": config.SERVICE_KEY,
                "content-type": "application/json",
            },
            json={"userId": user_id, "excludeSessionId": session_id or ""},
            timeout=min(config.RETRIEVAL_TIMEOUT_S, 5.0),
        )
        response.raise_for_status()
        turns = response.json().get("turns") or []
        return turns if isinstance(turns, list) else []

    async def retrieve(self, ctx: RetrievalContext) -> RetrievalResult:
        # No verified user, no private data. This is the check that stops one
        # person's consultation history reaching another's prompt.
        if not ctx.user_id:
            return RetrievalResult(section=self.section, chunks=())

        try:
            turns = await asyncio.to_thread(self._fetch, ctx.user_id, ctx.session_id)
        except Exception as error:  # noqa: BLE001
            # Memory is an enhancement. Convex being slow or down degrades the
            # answer; it must never fail the consultation.
            print(f"[memory] retrieval failed: {error}")
            return RetrievalResult(section=self.section, chunks=())

        # Oldest first so the model reads them as a narrative rather than in
        # reverse; Convex returns newest first.
        ordered = list(reversed(turns))[-MAX_TURNS:]

        chunks = tuple(
            Chunk(
                text=f"{'User' if t.get('role') == 'user' else 'Assistant'}: "
                f"{(t.get('content') or '').strip()[:MAX_CHARS]}",
                source=f"memory:{t.get('sessionId', 'past')}",
                # No similarity score: this is not a ranked search, it is the
                # most recent history. A fabricated score would imply otherwise.
                score=None,
                metadata={
                    "role": t.get("role", ""),
                    "kind": t.get("kind", ""),
                    "createdAt": t.get("createdAt"),
                },
            )
            for t in ordered
            if (t.get("content") or "").strip()
        )
        return RetrievalResult(section=self.section, chunks=chunks)
