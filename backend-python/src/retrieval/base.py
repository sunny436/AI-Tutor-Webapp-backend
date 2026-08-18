"""
retrieval/base.py
-----------------
The contract every knowledge source implements.

This is the seam the future RAG pipeline plugs into. The target flow is:

    user message
      -> user history & knowledge      (order 10)
      -> previous conversations        (order 20)
      -> medical profile               (order 30)
      -> uploaded reports              (order 40)
      -> vector search over notes      (order 50)   <- the only one live today
      -> build final prompt
      -> LLM

Adding a stage later means writing one `Retriever` and adding one line to
`registry.py`. Nothing else in the consultation flow changes.

DESIGN RULE — retrievers fetch, they never receive.
`RetrievalContext` carries *identifiers* (who is asking) and *this turn's text*,
never bulk data forwarded from the browser. Conversation history, the medical
profile and uploaded reports are server-owned data living in Convex; if the client
sent them, the browser could assert its own medical history to the model. So the
principal is threaded through now — unused — and enabling those retrievers later
requires no client change at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable



@dataclass(frozen=True)
class RetrievalContext:
    """Everything a retriever is allowed to know about the current turn."""

    # What to search for: the problem plus the labels the user actually clicked.
    query: str
    problem: str = ""
    # Human-readable "Question: Answer" lines collected so far.
    intake_summary: str = ""

    # WHICH BOT IS ASKING — and therefore which knowledge it may see.
    #
    # Resolved server-side from a validated `bot_id`, never from an unvalidated

    # Who is asking. Populated from a verified Convex JWT, never from the body.
    # Unused today; the four server-owned retrievers will need it.
    user_id: str | None = None
    session_id: str | None = None
    auth_token: str | None = None

    locale: str = "en"
    extras: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    """One retrieved passage."""

    text: str
    # Where it came from, e.g. "knowledge:digestion.md" or "convex:consults".
    source: str
    score: float | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResult:
    """What one retriever contributed, plus the prompt heading it belongs under."""

    section: str
    chunks: Sequence[Chunk] = ()

    @property
    def is_empty(self) -> bool:
        return len(self.chunks) == 0


@runtime_checkable
class Retriever(Protocol):
    """A knowledge source.

    `enabled=False` retrievers MUST still return an empty `RetrievalResult`
    rather than raising, so the assembly path is exercised in production from day
    one. Turning one on then becomes a flag flip plus a method body, with no
    integration risk.
    """

    name: str
    section: str
    order: int
    enabled: bool

    async def retrieve(self, ctx: RetrievalContext) -> RetrievalResult: ...
