"""
consult/memory_manager.py
--------------------------
Decides whether a completed turn carries a durable fact worth remembering
about this user, across conversations — distinct from `chat_history`
(state.py), which already survives within ONE conversation regardless of
curation and needs none of this.

This is genuinely new. The pre-`d7e6d42` architecture's memory retriever
(`retrieval/memory.py::PreviousConversationsRetriever`) replayed the last
few raw turns verbatim; nothing in this project's history ever decided
"is this worth keeping" or wrote a distilled fact anywhere.

STATUS — READ BEFORE WIRING THIS IN: the DECISION logic below (skip small
talk, ask the model whether a turn is worth remembering, extract a short
fact, check it isn't a near-duplicate of what's already known) is complete
and independently testable. The PERSISTENCE step is not: Convex's
`/backend/user-memory` route only supports READING raw turns
(`packages/backend/convex/memory.ts::recentTurns`) — there is no mutation to
write a curated fact anywhere. `persist_memory` raises `NotImplementedError`
naming exactly that gap, on purpose, rather than silently doing nothing
(which would look like memory creation "worked" when nothing was saved) or
crashing the turn as though a required feature had failed. Callers should
catch it and report memory creation as BLOCKED, not attempt to route around
it with a local store — see the module docstring in `retrieval/memory.py`
for why this backend should not grow its own database for something Convex
already owns.
"""

from __future__ import annotations

import asyncio
import json

from langchain_core.messages import HumanMessage

from src.consult.router import is_small_talk
from src.llm import invoke as llm_invoke

# Below this length a turn is essentially never a durable fact worth an LLM
# call to check — "ok", "haan", "thanks". Saves a call on the cases where the
# answer is obvious without one.
MIN_CHARS_TO_CONSIDER = 15

MEMORY_PROMPT = """A user said this to a wellness assistant, and the assistant replied.

Decide if this exchange contains a durable fact worth remembering for FUTURE
conversations with this same person — something like a chronic condition,
a lasting preference, or a pattern they described. Do NOT flag: greetings,
one-off questions with no lasting relevance, acknowledgements, or anything
already generic enough to apply to anyone.

Reply with ONLY a JSON object, no other text:
{{"worth_remembering": true or false, "fact": "a short third-person fact, or empty string"}}

The fact, if any, must be SHORT (under 20 words), specific to this person, and
written so it still makes sense read alone, weeks later, with no other context.

--- USER SAID ---
{user_text}

--- ASSISTANT REPLIED ---
{assistant_text}
"""


def _looks_trivial(user_text: str) -> bool:
    """Cheap pre-filter — skip the obvious cases without an LLM call."""
    text = (user_text or "").strip()
    if len(text) < MIN_CHARS_TO_CONSIDER:
        return True
    return is_small_talk(text)


def _classify_sync(user_text: str, assistant_text: str) -> tuple[bool, str]:
    raw = llm_invoke(
        [HumanMessage(content=MEMORY_PROMPT.format(
            user_text=user_text[:2000], assistant_text=assistant_text[:2000],
        ))],
        temperature=0.0,
        json_mode=True,
        max_tokens=200,
    )
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return False, ""
    return bool(parsed.get("worth_remembering")), str(parsed.get("fact") or "").strip()


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def is_duplicate(fact: str, existing_facts: list[str]) -> bool:
    """A cheap containment check, not embeddings — this is a lightweight
    curation layer, not the retrieval path. A fact is a duplicate if it (or
    an existing one) is a near-substring of the other once normalized."""
    normalized = _normalize(fact)
    if not normalized:
        return True
    for existing in existing_facts:
        existing_normalized = _normalize(existing)
        if not existing_normalized:
            continue
        if normalized in existing_normalized or existing_normalized in normalized:
            return True
    return False


async def curate_turn(
    user_text: str, assistant_text: str, existing_facts: list[str] | None = None
) -> str | None:
    """The full decision: skip trivial turns, ask the model, dedup. Returns
    the fact to remember, or None if this turn isn't worth keeping.

    Deliberately does NOT persist anything — see `persist_memory` and the
    module docstring for why that step is blocked, not just unwritten.
    """
    if _looks_trivial(user_text):
        return None
    try:
        worth_remembering, fact = await asyncio.to_thread(
            _classify_sync, user_text, assistant_text or ""
        )
    except Exception as error:  # noqa: BLE001
        # Fails soft, like every retrieval/memory path in this codebase — a
        # curation failure must not fail the turn the user is waiting on.
        print(f"[memory] curation call failed: {error}")
        return None
    if not worth_remembering or not fact:
        return None
    if is_duplicate(fact, existing_facts or []):
        return None
    return fact


def persist_memory(user_id: str, fact: str) -> None:
    """Write a curated fact so it survives across conversations.

    NOT IMPLEMENTED. There is no Convex mutation to call — see this module's
    docstring. Raise, rather than silently no-op, so a caller cannot mistake
    "nothing happened" for "it worked": catch this specific exception and
    report memory creation as BLOCKED.
    """
    raise NotImplementedError(
        "No Convex mutation exists to persist a curated memory fact — "
        "packages/backend/convex/memory.ts only exposes recentTurns (read-only). "
        "This needs a new Convex-side mutation before curated memory can be "
        "created; restoring PreviousConversationsRetriever's raw-turn read path "
        "does not require this and works today."
    )
