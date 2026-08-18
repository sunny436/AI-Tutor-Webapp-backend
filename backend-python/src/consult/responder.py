"""
consult/responder.py
--------------------
Turns everything collected into what the user actually asked for.

Two shapes of reply:

  `write_plan`     the structured consultation, containing only the sections the
                   user chose (root cause / food chart / yoga / …). The heading
                   strings come from `sections.py` and must match exactly, because
                   the UI colour-codes each one by name.

  `write_knowledge` a plain conversational answer to a general question, with no
                   headings — "what is ashwagandha?" doesn't need a daily routine.

The clicked intake answers arrive as clean "Question: Answer" lines, which are a
better input than the free-text paragraphs the old flow collected.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from langchain_core.messages import HumanMessage, SystemMessage

import config
from src import prompts
from src.consult.sections import SECTION_LIBRARY, render_section_spec
from src.llm import invoke as llm_invoke
from src.llm import stream as llm_stream

ANSWER_TEMPERATURE = 0.5

# Shown in place of the retrieved notes when nothing in the knowledge base was
# relevant enough. Stated plainly so the model knows to fall back to its own
# Ayurveda knowledge rather than inventing a source it was never given.
NO_KNOWLEDGE = "(no relevant notes found in the knowledge base for this question)"

FAILURE_MESSAGE = (
    "I couldn't complete your plan just now. Please try again in a moment — "
    "your answers have been kept."
)


def _invoke(prompt: str, on_token: Callable[[str], None] | None = None) -> str:
    """One answer. With `on_token`, pieces are handed over as they arrive.

    The return value is identical either way — the whole text — so callers and
    everything downstream (persistence, the ConsultResult contract, the
    non-streaming endpoint) are unaffected by which path ran. `on_token` only
    lets a reader start seeing the answer before it is finished.
    """
    messages = [
        SystemMessage(content=prompts.SYSTEM_RULES),
        HumanMessage(content=prompt),
    ]
    if on_token is None:
        return llm_invoke(
            messages,
            temperature=ANSWER_TEMPERATURE,
            max_tokens=config.MAX_TOKENS_ANSWER,
        )

    pieces: list[str] = []
    for piece in llm_stream(
        messages,
        temperature=ANSWER_TEMPERATURE,
        max_tokens=config.MAX_TOKENS_ANSWER,
    ):
        pieces.append(piece)
        on_token(piece)
    return "".join(pieces)


def _write_plan_sync(
    knowledge: str, profile: str, details: str, sections: list[str], language: str
) -> str:
    return _invoke(
        prompts.PLAN_PROMPT.format(
            system_rules=prompts.SYSTEM_RULES,
            knowledge=knowledge or NO_KNOWLEDGE,
            profile=profile or "No profile provided.",
            history=details,
            sections=render_section_spec(sections),
            # Empty would leave the prompt naming no language at all, which is
            # the state that produced the bug. Say "the user's own language" so
            # the instruction still reads as an instruction.
            language=language or "the user's own language and script",
        )
    )


async def write_plan(
    knowledge: str, profile: str, details: str, sections: list[str], language: str = ""
) -> str:
    """Generate the consultation plan, limited to the requested sections.

    `language` is the conversation's resolved language. It was missing here while
    every other writing path already took it, and this is the path that produces
    the thing the user actually asked for - so the plan was the one reply that
    could come back in the wrong language after a flawless English intake.
    """
    try:
        answer = await asyncio.to_thread(
            _write_plan_sync, knowledge, profile, details, sections, language
        )
    except Exception as error:  # noqa: BLE001
        print(f"[consult] plan generation failed: {error}")
        return FAILURE_MESSAGE

    _warn_if_incomplete(answer, sections, language)
    return answer


def _warn_if_incomplete(answer: str, sections: list[str], language: str) -> None:
    """Say so in the log when a plan came back missing its last section.

    A plan that overruns `MAX_TOKENS_ANSWER` stops mid-sentence and is returned
    with no error at all, so the failure is invisible: the user gets a plan that
    simply ends, and nothing upstream can tell that from a short answer.

    The section lost first is the LAST one, and `sections.ALWAYS_INCLUDED` exists
    precisely so that one - "When To See A Doctor" - can never be dropped. A
    silent truncation defeats that guarantee, which is why this warns rather than
    staying quiet about a merely cosmetic problem.

    Deliberately a log line and not an exception: a truncated plan is still worth
    more to the reader than a failure message, and `graph.py` has no better
    answer to substitute. This exists so the problem is discoverable, not so it
    can be handled.
    """
    if not answer or answer == FAILURE_MESSAGE:
        return
    expected = [SECTION_LIBRARY[s][0] for s in sections if s in SECTION_LIBRARY]
    if not expected:
        return
    lines = {line.strip() for line in answer.splitlines()}
    missing = [heading for heading in expected if heading not in lines]
    if missing:
        print(
            f"[consult] plan is missing {len(missing)}/{len(expected)} headings "
            f"({', '.join(missing)}) - language={language or 'unset'}, "
            f"{len(answer)} chars. Suspect MAX_TOKENS_ANSWER "
            f"({config.MAX_TOKENS_ANSWER}) if the text also ends mid-sentence."
        )


def _rework_sync(previous: str, request: str, language: str) -> str:
    return _invoke(
        prompts.FOLLOWUP_PROMPT.format(
            system_rules=prompts.SYSTEM_RULES,
            previous=previous,
            request=request,
            language=language or "the same language as the request",
        )
    )


async def rework_answer(previous: str, request: str, language: str = "") -> str:
    """Re-present the previous answer — translated, simplified, summarised or expanded.

    Deliberately does NOT go near retrieval: the user is pointing at text already
    on their screen, so searching the knowledge base again would answer a
    different question and lose what they asked about.

    `language` is the conversation's remembered language, already resolved by the
    caller. Passing it beats letting the model infer: "tell me more" carries no
    language signal at all, so inference flipped an English thread to Hinglish.
    """
    try:
        return await asyncio.to_thread(_rework_sync, previous, request, language)
    except Exception as error:  # noqa: BLE001
        print(f"[consult] follow-up rework failed: {error}")
        return FAILURE_MESSAGE


def _supportive_sync(problem: str, language: str) -> str:
    return _invoke(
        prompts.SUPPORTIVE_CARE_PROMPT.format(
            system_rules=prompts.SYSTEM_RULES,
            problem=problem,
            language=language or "the same language the user wrote in",
        )
    )


async def write_supportive_care(problem: str, language: str = "") -> str:
    """Reply to a serious diagnosed condition — cancer, TB, dialysis, transplant.

    Generated, not canned. The first version was a fixed paragraph: safe, but
    identical for every illness, stuck in one language, and it left the user
    nowhere to go. The model knows what supportive care looks like for the
    specific condition, so it can name it and OFFER it instead of only declining.

    No retrieval on purpose — the corpus has no note for these conditions and
    never will, so a search would only surface something about acidity.
    """
    try:
        return await asyncio.to_thread(_supportive_sync, problem, language)
    except Exception as error:  # noqa: BLE001
        print(f"[consult] supportive-care reply failed: {error}")
        # Fall back to the static text, so a model outage still produces a safe
        # and appropriate answer rather than a generic failure line.
        from src import safety

        return safety.SERIOUS_CONDITION_MESSAGE


def _write_knowledge_sync(
    question: str,
    knowledge: str,
    language: str,
    on_token: Callable[[str], None] | None = None,
) -> str:
    return _invoke(
        prompts.KNOWLEDGE_ANSWER_PROMPT.format(
            system_rules=prompts.SYSTEM_RULES,
            knowledge=knowledge or NO_KNOWLEDGE,
            question=question,
            language=language or "the same language as the question",
        ),
        on_token,
    )


async def write_knowledge(
    question: str,
    knowledge: str,
    language: str = "",
    on_token: Callable[[str], None] | None = None,
) -> str:
    """Answer a general Ayurveda/Yoga question conversationally.

    `on_token` is optional and changes nothing about the result: the full answer
    is still returned and still persisted the same way. It exists so a caller
    that wants to show the reply as it is written can, without this function
    needing to know anything about transports or endpoints.
    """
    try:
        return await asyncio.to_thread(
            _write_knowledge_sync, question, knowledge, language, on_token
        )
    except Exception as error:  # noqa: BLE001
        print(f"[consult] knowledge answer failed: {error}")
        return (
            "I couldn't look that up just now. Please try again — or tell me what's "
            "troubling you and I'll put together a full plan."
        )
