"""
consult/gathering.py
--------------------
Asking about a complaint in PROSE. This is what replaced `planner.py`'s cards.

WHAT CHANGED AND WHY
The consultation used to answer "mujhe gas ho rahi hai" with a five-card
questionnaire. That is a form, not a conversation, and it forced everyone down
the same funnel regardless of how much they had already said. Now the assistant
asks one or two questions the way a person would, and keeps the thread.

THIS IS NOT A SECOND ANSWER GENERATOR
It asks questions; GraphRAG's /v1/answer writes the final plan, scoped to one
note. Same relationship `router.py` already has —
that one writes greetings and refusals the user reads, on the same single model
chain. This uses `llm.invoke` exactly as both of them do: no second provider, no
separate service, no vendor `/v1/answer`.

It also inherits `PERSONA_CORE` (see prompts.GATHERING_PROMPT), so the language
rule, the never-name-a-medicine rule and the not-a-doctor rule apply to these
questions as much as to the final plan.

WHAT IT RETURNS, AND WHY EACH FIELD EXISTS
    reply      the questions, in the conversation's language
    condition  short English label, used for retrieval and the UI heading
    symptoms   SHORT keywords -> the vector query. See `state.search_query`.
    red_flag   the replacement for the planner's per-option `red_flag` markers
    ready      "I know enough" — the signal the card flow got for free from
               "every question has been answered"

FAILURE DIRECTION
Fails SAFE, not open. If the model is unreachable or returns nonsense, the turn
falls back to a fixed question in the user's language rather than proceeding to
write a plan out of nothing. Better to ask once more than to answer blind.
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import HumanMessage

import config
from src import prompts
from src.consult.repair import extract_json
from src.llm import invoke as llm_invoke

# Low, but not zero. These are questions about someone's health: they should read
# as though a person asked them, and 0.0 produced the same two sentences for
# every complaint. Matches the planner's old setting so the change of flow does
# not also silently change the model's temperament.
GATHERING_TEMPERATURE = 0.4

# Hard ceiling on how long an intake can run. The prompt already tells the model
# to finish by round 4; this is the guard for when it does not listen, because an
# assistant that keeps asking questions forever is worse than one that answers
# with slightly less detail.
MAX_GATHERING_ROUNDS = 4

MAX_REPLY_CHARS = 700
MAX_SYMPTOM_WORDS = 4

# Used when the model cannot be reached at all. Deliberately a real question, so
# the conversation still moves rather than dead-ending on an apology.
_FALLBACK_QUESTION = {
    "english": "Tell me a little more — how long has this been going on, and does anything make it better or worse?",
    "hinglish": "Thoda aur bataiye — ye kab se ho raha hai, aur kisi cheez se kam ya zyada hota hai?",
    "devanagari": "थोड़ा और बताइए — यह कब से हो रहा है, और किसी चीज़ से कम या ज़्यादा होता है?",
}


class Gathered:
    """One gathering turn's outcome."""

    __slots__ = ("reply", "condition", "symptoms", "red_flag", "ready")

    def __init__(
        self,
        reply: str = "",
        condition: str = "",
        symptoms: list[str] | None = None,
        red_flag: bool = False,
        ready: bool = False,
    ) -> None:
        self.reply = reply
        self.condition = condition
        self.symptoms = symptoms or []
        self.red_flag = red_flag
        self.ready = ready


def _clean_symptoms(raw) -> list[str]:
    """Keep only things short enough to be search keywords.

    The model is told "1-3 words" and mostly complies, but one sentence slipping
    through would land straight in the vector query, and that is the exact
    dilution `state.search_query` documents (0.408 -> 0.172). So it is enforced
    here rather than hoped for.
    """
    if not isinstance(raw, list):
        return []
    kept = []
    for item in raw:
        text = str(item or "").strip().strip(".,;")
        if not text or len(text.split()) > MAX_SYMPTOM_WORDS:
            continue
        kept.append(text[:40])
    return kept


def _gather_sync(
    problem: str, history: str, symptoms: list[str], language: str, rounds: int
) -> Gathered:
    raw = llm_invoke(
        [
            HumanMessage(
                content=prompts.GATHERING_PROMPT.format(
                    problem=problem or "(not described)",
                    history=history or "(this is the first message)",
                    symptoms=", ".join(symptoms) or "(nothing yet)",
                    language=language or "hinglish",
                    rounds=rounds,
                )
            )
        ],
        temperature=GATHERING_TEMPERATURE,
        json_mode=True,
        max_tokens=config.MAX_TOKENS_PLANNER,
    )

    parsed = extract_json(raw) or {}
    return Gathered(
        reply=str(parsed.get("reply") or "").strip()[:MAX_REPLY_CHARS],
        condition=str(parsed.get("condition") or "").strip()[:80],
        symptoms=_clean_symptoms(parsed.get("symptoms")),
        red_flag=bool(parsed.get("red_flag")),
        ready=bool(parsed.get("ready")),
    )


async def gather(
    *,
    problem: str,
    history: str = "",
    symptoms: list[str] | None = None,
    language: str = "",
    rounds: int = 0,
) -> Gathered:
    """Ask the next question, and report what has been understood so far."""
    try:
        result = await asyncio.to_thread(
            _gather_sync, problem, history, list(symptoms or []), language, rounds
        )
    except Exception as error:  # noqa: BLE001
        print(f"[consult] gathering failed: {error}")
        # NOT `ready=True`. A model outage must not cause a plan to be written
        # from whatever happens to be in context — that is how someone gets
        # advice for a complaint nobody understood.
        return Gathered(reply=_FALLBACK_QUESTION.get(language, _FALLBACK_QUESTION["hinglish"]))

    # The hard ceiling. The prompt asks for this and is not always obeyed.
    if rounds >= MAX_GATHERING_ROUNDS:
        result.ready = True

    # An empty reply would render an empty bubble. If the model has nothing to
    # ask, that is itself the signal that it has enough.
    if not result.reply and not result.ready:
        result.ready = True

    return result
