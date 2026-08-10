"""
consult/planner.py
------------------
The LLM call that designs the intake form.

This is what makes the flow AI-driven rather than hardcoded: the model reads the
user's problem and writes the questions AND their options. Acidity gets food and
bowel questions; migraine gets trigger and aura questions; PCOS gets cycle
questions — none of which appear anywhere in this codebase.

Failure direction depends on the round, which is the important detail:
  - round 1 fails CLOSED  -> the baseline plan, so the screen is never empty
  - round 2 fails OPEN    -> proceed to the answer with whatever was collected
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import HumanMessage

import config
from src import prompts
from src.consult.fallback import baseline_plan
from src.consult.repair import parse_plan
from src.consult.router import detect_language
from src.consult.schema import IntakePlan
from src.llm import invoke as llm_invoke

PLANNER_TEMPERATURE = 0.3


def _invoke(prompt: str) -> str:
    return llm_invoke(
        [HumanMessage(content=prompt)],
        temperature=PLANNER_TEMPERATURE,
        json_mode=True,
        max_tokens=config.MAX_TOKENS_PLANNER,
    )


def _plan_sync(problem: str, collected: str, language: str = "") -> IntakePlan:
    # Language is decided in code, not by the model. This call gets no system
    # prompt and its JSON schema example is written in English, so "mujhe acidity
    # hai" kept producing "How often do you experience acidity?" with English
    # options — while the plan built from those same answers came back in Hinglish.
    #
    # `language` is passed IN by the caller rather than detected from `problem`,
    # because `problem` is the ROUTER'S RESTATEMENT, not the user's words. The
    # router rewrites "मुझे खाना खाने के बाद गैस होती है" to a short Latin summary
    # ("gais"), so detecting here saw Latin text and planned an entire Hinglish
    # questionnaire for someone who wrote in Devanagari. The caller already holds
    # the language detected from what the user actually typed.
    #
    # Falling back to detection keeps the old behaviour for any caller that has
    # no context to offer.
    prompt = prompts.INTAKE_PLAN_PROMPT.format(
        problem=problem or "(not described)",
        collected=collected or "(nothing yet)",
        language=language or detect_language(problem),
    )

    plan = parse_plan(_invoke(prompt))
    if plan.questions:
        return plan

    # One retry, never two — each attempt costs 1-3 seconds of the user's time.
    retry = (
        prompt
        + "\n\nYour previous reply could not be parsed into questions. "
        "Reply with ONLY the JSON object described above."
    )
    return parse_plan(_invoke(retry))


async def plan_intake(
    problem: str, collected: str, round_number: int, language: str = ""
) -> IntakePlan:
    """Design the next set of question cards.

    `language` is the conversation's sticky language, detected from what the USER
    typed. Pass it — see `_plan_sync` for why detecting it from `problem` here
    produces a Hinglish questionnaire for a Devanagari speaker.

    Returns a plan with `questions == []` only when round >= 2 planning failed,
    which the caller reads as "stop asking and answer".
    """
    try:
        # LangChain's invoke is blocking; keep it off the event loop.
        plan = await asyncio.to_thread(_plan_sync, problem, collected, language)
    except Exception as error:  # noqa: BLE001
        print(f"[consult] planner call failed: {error}")
        plan = IntakePlan()

    if plan.questions:
        return plan

    if round_number <= 1:
        # Fail closed: an empty first round would show the user nothing to click.
        print("[consult] round 1 planning failed - using baseline plan")
        return baseline_plan()

    # Fail open: we already have answers, so an answer is better than a retry.
    print(f"[consult] round {round_number} planning failed - proceeding to answer")
    return IntakePlan()
