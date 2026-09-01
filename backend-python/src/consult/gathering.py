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
It asks questions; `consult/responder.py::write_plan` writes the final plan.
Same relationship `router.py` already has — that one writes greetings and
refusals the user reads, on the same single model chain. This uses
`llm.invoke` exactly as both of them do: no second provider, no separate
service, no vendor `/v1/answer`.

(This paragraph used to say GraphRAG's `/v1/answer` wrote the plan. It did,
once. That endpoint was removed rather than left unused — see
`retrieval/graphrag.py`'s module docstring for why — and GraphRAG now only
retrieves, through `/v1/search`. Left uncorrected, a comment like that is an
invitation to wire the vendor's own prose generation back in.)

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

    __slots__ = (
        "reply", "condition", "symptoms", "missing_info",
        "profile_facts", "profile_removals", "red_flag", "ready",
    )

    def __init__(
        self,
        reply: str = "",
        condition: str = "",
        symptoms: list[str] | None = None,
        missing_info: list[str] | None = None,
        profile_facts: dict | None = None,
        profile_removals: dict | None = None,
        red_flag: bool = False,
        ready: bool = False,
    ) -> None:
        self.reply = reply
        self.condition = condition
        self.symptoms = symptoms or []
        self.missing_info = missing_info or []
        # Long-term facts the person stated THIS turn. Extracted in the same
        # JSON call as everything else, so a profile costs no extra latency
        # and no second model round trip.
        self.profile_facts = profile_facts or {}
        # Facts they have just TAKEN BACK — "maine metformin band kar diya".
        # `state.merge_profile` has always accepted a `removals` argument and
        # nothing ever supplied one, so a stopped medicine stayed on the
        # profile for good and every later turn kept treating it as current.
        # Removal stays explicit-only: silence is never a retraction, which is
        # why this is a separate field and not an absence from `profile_facts`.
        self.profile_removals = profile_removals or {}
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
    problem: str, history: str, symptoms: list[str], language: str, rounds: int,
    missing: list[str] | None = None, profile: str = "", serious: str = "",
) -> Gathered:
    missing = missing or []
    raw = llm_invoke(
        [
            HumanMessage(
                content=prompts.GATHERING_PROMPT.format(
                    problem=problem or "(not described)",
                    history=history or "(this is the first message)",
                    symptoms=", ".join(symptoms) or "(nothing yet)",
                    missing=", ".join(missing) or "(nothing noted yet)",
                    profile=profile or "(they have not told you anything about themselves yet)",
                    serious=(
                        prompts.SERIOUS_CONDITION_MODE.format(condition=serious)
                        if serious else ""
                    ),
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
        missing_info=_clean_symptoms(parsed.get("missing_info")),
        profile_facts=parsed.get("profile_facts") if isinstance(parsed.get("profile_facts"), dict) else {},
        profile_removals=(
            parsed.get("profile_removals")
            if isinstance(parsed.get("profile_removals"), dict)
            else {}
        ),
        red_flag=bool(parsed.get("red_flag")),
        ready=bool(parsed.get("ready")),
    )


async def gather(
    *,
    problem: str,
    history: str = "",
    symptoms: list[str] | None = None,
    missing_info: list[str] | None = None,
    profile: str = "",
    serious_condition: str = "",
    language: str = "",
    rounds: int = 0,
) -> Gathered:
    """Ask the next question, and report what has been understood so far."""
    try:
        result = await asyncio.to_thread(
            _gather_sync, problem, history, list(symptoms or []), language, rounds,
            list(missing_info or []), profile, serious_condition,
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

    # Enforced, not just prompted: "missing_info" describes what the NEXT
    # question would ask about, so it means nothing once there is no next
    # question. Same "enforce in code, don't just hope the model listens"
    # pattern MAX_GATHERING_ROUNDS already uses above.
    if result.ready:
        result.missing_info = []

    return result


_VALID_HELP_TYPES = ("root_cause", "remedies", "yoga", "diet", "complete")


def _classify_focus_sync(reply: str) -> list[str]:
    raw = llm_invoke(
        [HumanMessage(content=prompts.FOCUS_CLASSIFY_PROMPT.format(reply=reply))],
        temperature=0.0,
        json_mode=True,
        max_tokens=60,
    )
    parsed = extract_json(raw) or {}

    # Tolerate the old single-string shape as well as the list. The prompt
    # asks for `help_types`, but a model that answers with the previous
    # `help_type` key, or with a bare string, should still be understood
    # rather than silently falling back to "complete".
    raw_values = parsed.get("help_types")
    if raw_values is None:
        raw_values = parsed.get("help_type")
    if isinstance(raw_values, str):
        raw_values = [raw_values]
    if not isinstance(raw_values, list):
        # Unreadable shape — not the same thing as "they didn't choose". Fall
        # back to the whole plan, as this has always done.
        return ["complete"]

    kept: list[str] = []
    for value in raw_values:
        cleaned = str(value or "").strip().lower()
        if cleaned in _VALID_HELP_TYPES and cleaned not in kept:
            kept.append(cleaned)

    # AN EMPTY LIST IS A REAL ANSWER, NOT A FAILURE, and must survive back to
    # the caller. It means the model read the reply and decided it is not a
    # choice at all — a question, an aside, something unrelated. This used to
    # collapse to ["complete"], which is how "Tell me something about
    # Ayurveda", typed at the focus question, produced a full six-section
    # acidity plan instead of an answer. `graph.py` decides what to do with
    # it; the one thing that must not happen is silently inventing a choice
    # the user never made.
    return kept


async def classify_focus(reply: str, language: str = "") -> list[str]:
    """Which of the five sections they want, from their free-text reply to
    the focus question (graph.py's `_FOCUS_QUESTION`).

    Returns EVERY category asked for, because asking for two at once ("yoga
    and diet", "root cause and complete plan both") is an ordinary answer to
    that question, and returning only the first silently gave the user less
    than they asked for.

    Returns an EMPTY LIST when the reply is not an answer to the focus
    question at all — a question of their own, an aside, something unrelated.
    That is a verdict, not a failure, and the caller must handle it: `graph.py`
    answers the reply and leaves the conversation in `asking_focus` rather
    than picking a focus nobody asked for.

    Still defaults to `["complete"]` for a genuine FAILURE — an unreachable
    model or an unreadable response — because an outage should not dead-end
    somebody who has already finished gathering. The distinction matters:
    "the model says this isn't a choice" and "we could not ask the model" look
    identical from the outside and must not behave identically.
    """
    try:
        return await asyncio.to_thread(_classify_focus_sync, reply)
    except Exception as error:  # noqa: BLE001
        print(f"[consult] focus classification failed: {error}")
        return ["complete"]
