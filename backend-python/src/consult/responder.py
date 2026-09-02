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

import re

import asyncio
from typing import Callable

from langchain_core.messages import HumanMessage, SystemMessage

import config
from src import prompts, safety
from src.consult import evidence
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
    knowledge: str,
    profile: str,
    details: str,
    sections: list[str],
    language: str,
    section_evidence: dict[str, bool] | None,
) -> str:
    # The `or NO_KNOWLEDGE` fallback only applies when nothing computed
    # per-section evidence — with it, the per-section [Evidence: ...] tags in
    # `sections` are the authoritative signal, and the old whole-block marker
    # text sitting inside `{knowledge}` would (a) contradict a section tagged
    # SUPPORTED and (b) hand the model the words "knowledge base" to
    # potentially echo back, exactly what rule 14 now forbids saying.
    resolved_knowledge = (
        knowledge if section_evidence is not None else (knowledge or NO_KNOWLEDGE)
    )
    return _invoke(
        prompts.PLAN_PROMPT.format(
            system_rules=prompts.SYSTEM_RULES,
            knowledge=resolved_knowledge,
            profile=profile or "No profile provided.",
            history=details,
            sections=render_section_spec(sections, section_evidence),
            # Empty would leave the prompt naming no language at all, which is
            # the state that produced the bug. Say "the user's own language" so
            # the instruction still reads as an instruction.
            language=language or "the user's own language and script",
        )
    )


async def write_plan(
    knowledge: str,
    profile: str,
    details: str,
    sections: list[str],
    language: str = "",
    section_evidence: dict[str, bool] | None = None,
) -> str:
    """Generate the consultation plan, limited to the requested sections.

    `language` is the conversation's resolved language. It was missing here while
    every other writing path already took it, and this is the path that produces
    the thing the user actually asked for - so the plan was the one reply that
    could come back in the wrong language after a flawless English intake.

    `section_evidence` is `consult.evidence.evaluate_sections`'s output — which
    of `sections` have real grounded material behind them. `None` (the
    default) renders every section with no evidence tag, i.e. today's
    behaviour, for any caller that hasn't adopted this.
    """
    try:
        answer = await asyncio.to_thread(
            _write_plan_sync, knowledge, profile, details, sections, language, section_evidence
        )
    except Exception as error:  # noqa: BLE001
        print(f"[consult] plan generation failed: {error}")
        return FAILURE_MESSAGE

    _warn_if_incomplete(answer, sections, language)
    _warn_if_medicine(answer)
    _warn_if_leaked_terms(answer)
    return answer


def _warn_if_medicine(answer: str) -> None:
    """Say so in the log when a plan named a drug or gave a dose.

    Rule 2 was widened to permit Ayurvedic herbs by name, and a widened rule needs
    a way to notice when it has been overshot. `safety.names_medicine` is a
    keyword backstop, not a filter: it reports and never rewrites, because a regex
    quietly deleting part of a health answer is a worse failure than the one it
    would be preventing.
    """
    found = safety.names_medicine(answer)
    if found:
        print(
            f"[consult] plan mentions {found!r} - rule 2 permits Ayurvedic herbs "
            "by name but never a drug, a brand or a dose."
        )
    # Louder, because it is worse. Naming a prescribed drug as the reason the
    # person feels unwell is how an answer talks somebody off their treatment
    # without ever using the word "stop". See safety.blames_medicine.
    blamed = safety.blames_medicine(answer)
    if blamed:
        print(
            "[consult] PLAN BLAMED A PRESCRIBED MEDICINE for the complaint - "
            f"rule 2 forbids this outright: ...{blamed[:160]!r}..."
        )


def _warn_if_leaked_terms(answer: str) -> None:
    """Say so in the log when a plan named its own retrieval system.

    Same backstop role as `_warn_if_medicine` — `prompts.PLAN_PROMPT` rule 14
    and the per-section evidence tags (`sections.render_section_spec`) are
    what should prevent this; this only reports when they didn't, rather than
    rewriting the answer. See consult/evidence.py::find_leaked_terms.
    """
    found = evidence.find_leaked_terms(answer)
    if found:
        print(
            f"[consult] plan leaked internal terms {found!r} - rule 14 and the "
            "per-section evidence tags should have kept these out of a "
            "user-facing answer."
        )


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


# Does this reply actually hand them something to do? A named technique, not
# the word "yoga" - and not merely mentioned inside a question, which is how
# the model kept passing a looser check while still asking for clinical detail.
_PRACTICE_GIVEN = re.compile(
    r"(pranayam|dirgha|anulom|bhramari|shavasana|deep breath|gehri saans|"
    r"dheemi saans|belly breath|ankle|wrist|kalai|panj|stretch|walk|tehal|"
    r"ghuma|rotation)",
    re.IGNORECASE,
)


def _gives_a_practice(reply: str) -> bool:
    """True when the reply names something to do OUTSIDE a question."""
    body = reply or ""
    # Drop every sentence that ends in a question mark, then look again.
    statements = " ".join(
        part for part in re.split(r"(?<=[.!?])\s+", body) if not part.strip().endswith("?")
    )
    return bool(_PRACTICE_GIVEN.search(statements))


def _supportive_continue_sync(
    context: str, request: str, language: str, directive: str
) -> str:
    return _invoke(
        prompts.SUPPORTIVE_CONTINUE_PROMPT.format(
            system_rules=prompts.SYSTEM_RULES,
            context=context,
            request=request,
            directive=directive,
            language=language or "the same language the user wrote in",
        )
    )


async def write_supportive_continue(
    context: str, request: str, language: str = "", *, deliver: bool = False
) -> str:
    """The turns AFTER the standing position has been stated once.

    `write_supportive_care` opens: it acknowledges the diagnosis and says that
    the doctor's treatment is the treatment. Calling it again for every later
    turn is what made the assistant repeat itself at somebody who was only
    rephrasing the same request. This writes the reply that moves instead —
    the symptom check first, then conservative guidance — and it is the only
    difference between the two paths.

    Falls back to the opening reply rather than to nothing: repeating is bad,
    saying nothing useful in a serious conversation is worse.
    """
    try:
        directive = (
            prompts.SUPPORTIVE_GIVE_GUIDANCE if deliver
            else prompts.SUPPORTIVE_ASK_SYMPTOMS
        )
        reply = await asyncio.to_thread(
            _supportive_continue_sync, context, request, language, directive
        )
        # RETRY ONCE IF IT ASKED INSTEAD OF ANSWERING.
        #
        # Same backstop `write_safety_first` uses for a named practice: the
        # instruction is in the prompt, and the model still sometimes returns
        # a question. On the turn where guidance is due that is the original
        # complaint all over again - the person asked, and got asked back. So
        # the output is checked and one blunter attempt is made.
        if deliver and not _gives_a_practice(reply):
            print("[consult] supportive reply asked instead of answering; retrying once")
            retry = await asyncio.to_thread(
                _supportive_continue_sync,
                context,
                request,
                language,
                prompts.SUPPORTIVE_GIVE_GUIDANCE + prompts.SUPPORTIVE_DELIVER_HARDER,
            )
            if _gives_a_practice(retry):
                return retry
        return reply
    except Exception as error:  # noqa: BLE001
        print(f"[consult] supportive-continue reply failed: {error}")
        return await write_supportive_care(context, language)


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


def _safety_first_sync(
    problem: str, request: str, reason: str, language: str, avoid: str = ""
) -> str:
    # `avoid` quotes the offending word back on a retry. Same technique
    # `router._route_sync` uses for a repeated reply, and for the same reason:
    # naming what went wrong works where re-asking the same way does not.
    correction = (
        f"\n\nYOUR PREVIOUS ATTEMPT USED THE WORD \"{avoid}\". Do not use it, or "
        "any other name of a yoga posture or breathing technique, anywhere in "
        "the reply. Refer to what they asked for in plain words instead — "
        "\"yoga\", \"breathing exercises\", \"a home remedy\"."
        if avoid
        else ""
    )
    return _invoke(
        prompts.SAFETY_FIRST_PROMPT.format(
            system_rules=prompts.SYSTEM_RULES,
            problem=problem or "(not described in words)",
            request=request or "(they did not ask for anything specific)",
            reason=reason or "something in this conversation needs prompt medical attention",
            language=language or "the same language the user wrote in",
        )
        + correction
    )


async def write_safety_first(
    problem: str, request: str, reason: str = "", language: str = ""
) -> str:
    """The reply for a conversation that has already shown a red flag.

    Generated rather than canned, for the same reason `write_supportive_care`
    below is: `safety.ESCALATION_MESSAGE` is one fixed paragraph, so it cannot
    explain why THIS person's situation needs looking at, and it cannot
    respond to what they just asked for. Somebody who asked "can you tell me
    some yoga?" after saying they could not keep fluids down deserves to hear
    why yoga is the wrong thing right now — not the same paragraph again.

    Falls back to `ESCALATION_MESSAGE` on ANY failure. That is the whole point
    of keeping the fixed string: a model outage must still produce a safe,
    correct reply, never silence and never a wellness plan.
    """
    try:
        answer = await asyncio.to_thread(
            _safety_first_sync, problem, request, reason, language
        )
    except Exception as error:  # noqa: BLE001
        print(f"[consult] safety-first reply failed: {error}")
        return safety.ESCALATION_MESSAGE

    if not (answer or "").strip():
        return safety.ESCALATION_MESSAGE

    # A SAFETY REPLY MAY NOT NAME A PRACTICE, AND THIS IS ENFORCED RATHER THAN
    # ASKED FOR.
    #
    # The prompt has a conflict built into it: rule 1 tells the model to
    # acknowledge what they asked for BY NAME, so a request for yoga reliably
    # produced "yoga aur pranayama abhi na karein" — a correct prohibition
    # containing a word that, to somebody skimming an alarming message, reads
    # like a suggestion. It failed about one run in three, which is exactly the
    # rate at which a prompt rule is "mostly" followed.
    #
    # Retry once quoting the word back, then fall through to the fixed
    # ESCALATION_MESSAGE. Unlike everywhere else in this file, this is NOT
    # report-only: the fallback is a complete, safe, correct reply, so there is
    # a good answer to fall back TO. `_warn_if_medicine` has no such luxury —
    # dropping a plan would leave nothing.
    named = safety.names_practice(answer)
    if named:
        print(f"[safety] reply named a practice ({named!r}); retrying once")
        try:
            retry = await asyncio.to_thread(
                _safety_first_sync, problem, request, reason, language, named
            )
        except Exception as error:  # noqa: BLE001
            print(f"[consult] safety-first retry failed: {error}")
            retry = ""
        still = safety.names_practice(retry)
        if retry.strip() and not still:
            answer = retry
        else:
            print(
                f"[safety] retry still named a practice ({still!r}); "
                "falling back to the fixed escalation message"
            )
            return safety.ESCALATION_MESSAGE

    # A safety reply that names a herb or a dose is the worst possible version
    # of this, so it is checked rather than assumed. Report-only, like
    # everywhere else - see `_warn_if_medicine`.
    _warn_if_medicine(answer)
    _warn_if_leaked_terms(answer)
    return answer


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
        answer = await asyncio.to_thread(
            _write_knowledge_sync, question, knowledge, language, on_token
        )
        # Same log-only backstops write_plan already runs. A general answer can
        # name a drug or echo "knowledge base" just as easily as a plan can,
        # and until now nothing would have said so.
        _warn_if_medicine(answer)
        _warn_if_leaked_terms(answer)
        return answer
    except Exception as error:  # noqa: BLE001
        print(f"[consult] knowledge answer failed: {error}")
        return (
            "I couldn't look that up just now. Please try again — or tell me what's "
            "troubling you and I'll put together a full plan."
        )
