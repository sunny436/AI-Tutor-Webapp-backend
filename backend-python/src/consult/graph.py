"""
consult/graph.py
----------------
The consultation flow.

    typed message -> route -+- greeting / about / off-topic -> conversational reply
                            +- general question -------------> retrieve -> short answer
                            +- health complaint -------------> gather (in prose)
                                                                   |
                                            replies <--------------+
                                                |          one or two questions
                                                v          a turn, until "ready"
                                        ask what kind of help they want
                                                |          conversational, not a menu
                                                v          (_FOCUS_QUESTION, classify_focus)
                                   retrieve -> plan (sections scoped to that choice)

GATHERING NEVER JUMPS STRAIGHT TO AN ANSWER. "ready" ends the QUESTIONS, not
the conversation — the very next thing is always the focus question
(phase="asking_focus"), never retrieval. GraphRAG is not reached, and no
plan is written, until that resolves to a `help_type`. See `_HELP_TYPE_SECTIONS`.

NO CARDS. The consultation used to answer "mujhe gas ho rahi hai" with a
five-card questionnaire and then a second card screen asking which parts of the
plan they wanted. Both were forms. The user is now never asked to pick from a
list, and never has to in order to reach a plan.

SAFETY, AFTER THE CARDS
The planner used to mark individual options `red_flag`, and safety.py describes
its own keyword scan as the BACKSTOP to those markers rather than the only
defence. Removing the cards removed the primary mechanism, so it is replaced by
three:
  1. `safety.scan` now reads the WHOLE conversation, not just the opening
     complaint (state.safety_fragments) - strictly more text than the labels it
     used to cover;
  2. the gathering step returns `red_flag` itself, having read the transcript;
  3. `safety.is_serious_condition` still runs on the problem and on retrieved
     report text, unchanged.

Written as plain async orchestration rather than a compiled StateGraph: the
branches are short, the state is a Pydantic model rather than a merge-able dict,
and every step is async I/O. A graph object would add indirection without buying
routing we need. The old `src/graph.py` LangGraph flow has been deleted; this is
now the only orchestration, and `/jobs/run` calls it too.
"""

from __future__ import annotations

import asyncio
import re
from typing import Callable

import config
from src import safety
from src.consult import evidence
from src.consult import state as ctx_state
from src.clinical import episodes as clinical_episodes
from src.clinical import evidence_class as clinical_evidence
from src.clinical import gate as clinical_gate
from src.clinical import triage as clinical_triage
from src.consult.gathering import MAX_GATHERING_ROUNDS, classify_focus, gather
from src.retrieval import graphrag
# `write_plan` generates the final answer from whatever the Context Builder
# assembled (memory + GraphRAG + local knowledge + uploaded reports). GraphRAG
# itself only retrieves now — see src/retrieval/graphrag.py's module docstring
# for why /v1/answer was removed rather than left unused.
from src.consult.responder import (
    NO_KNOWLEDGE,
    rework_answer,
    write_knowledge,
    write_plan,
    write_safety_first,
    write_supportive_care,
)
from src import patient_profile as profile_store
from src.knowledge import match_topics
from src.consult.router import (
    CONVERSATIONAL,
    asks_for_guidance_now,
    Route,
    detect_language,
    has_health_signal,
    is_about_uploaded_document,
    is_continuation_request,
    is_followup_request,
    is_personal_complaint,
    is_small_talk,
    requested_language,
    route_message,
)
from src.consult.schema import CONSULTING, ConsultContext, ConsultResult
from src.consult.sections import SECTIONS_QUESTION_ID, looks_like_plan, resolve_sections
from src.retrieval.base import RetrievalContext
from src.retrieval.registry import get_pipeline

# Hard ceiling on gathering rounds now lives in `consult/gathering.py`, next to
# the prompt that also asks the model to stop. `config.MAX_INTAKE_ROUNDS` still
# exists and still applies to the legacy `/chat` path in src/graph.py.

# Replies for small talk typed while the cards are open. Fixed strings, not a
# model call: the whole point is that this path works with no LLM, and there is
# nothing to be creative about in answering "ok". Both point back at the cards,
# because that is what the user is actually in the middle of.
SMALL_TALK_REPLIES = {
    # These pointed at "upar wale sawaal" - the question CARDS. Those were removed
    # with the questionnaire, and no turn returns kind="intake" any more, so the
    # assistant was telling people to answer questions that are not on their
    # screen. It now points back at the conversation, which is what is actually
    # in front of them.
    "greeting": "Namaste! 🌿 Bataiye, apni takleef ke baare mein aur kya bata sakte hain?",
    "ack": "Theek hai 🙂 Jab taiyaar hon, thoda aur bata dijiye — phir main plan bana deta hoon.",
}

# The step between "gathering is ready" and "write the plan". Fixed strings,
# not a model call — asking is templated, only the free-text REPLY needs
# understanding (classify_focus). Deliberately conversational, not a menu:
# GATHERING_PROMPT rule 3 already forbids "no menus of options to pick
# from" for the same reason cards were removed everywhere else.
_FOCUS_QUESTION = {
    "hinglish": (
        "Theek hai, {condition} ke baare mein samajh aa gaya. Ab bataiye — "
        "kya jaanna chahenge: iska root cause, Ayurveda remedies, "
        "yoga aur breathing, diet/lifestyle, ya poora plan (sab kuch)?"
    ),
    "english": (
        "Alright, I have a good picture of your {condition} now. What would "
        "you like to focus on — the root cause, Ayurveda remedies, "
        "yoga & breathing, diet & lifestyle, or the complete plan?"
    ),
    "devanagari": (
        "ठीक है, {condition} के बारे में समझ आ गया। अब बताइए — रूट कॉज़, "
        "आयुर्वेदिक उपाय, योग व साँस, आहार, या पूरा प्लान?"
    ),
}

# help_type -> which SECTION_LIBRARY keys to write. None means "everything"
# (resolve_sections(None) -> DEFAULT_SECTIONS) — same table `classify_focus`
# is told to choose from; "medicine information" was deliberately folded
# into "remedies" rather than kept separate, since SYSTEM_RULES rule 2 still
# forbids naming a drug or a dose regardless of what the user asks for.
_HELP_TYPE_SECTIONS: dict[str, list[str] | None] = {
    "root_cause": ["root_cause"],
    "remedies": ["changes"],
    "yoga": ["yoga"],
    "diet": ["food"],
    "complete": None,
}


def _sections_for(help_types: list[str]) -> list[str] | None:
    """Union the section keys for every focus the user asked for.

    `None` means "everything", which is exactly what `resolve_sections`
    already does with an empty selection — so nothing chosen, and "complete"
    appearing anywhere in the list, both correctly mean the full plan rather
    than an empty one.

    Ordering, de-duplication and force-including "When To See A Doctor" are
    all left to `resolve_sections` / `ALWAYS_INCLUDED` (sections.py), which
    already do exactly that.
    """
    if not help_types or "complete" in help_types:
        return None
    keys: list[str] = []
    for help_type in help_types:
        keys.extend(_HELP_TYPE_SECTIONS.get(help_type) or [])
    return keys or None


_GREETING_WORDS = re.compile(
    r"^\s*(?:h+i+|h+e+y+|h+e+l+o+|hii+|hlo|yo|hola|namaste|namaskar"
    r"|नमस्ते|नमस्कार|good\s*(?:morning|afternoon|evening|night)"
    r"|kaise\s*ho|kya\s*haal|how\s*are\s*you|sup|wassup)",
    re.IGNORECASE,
)


def _looks_like_greeting(text: str) -> bool:
    """Greeting ("hii") versus a bare acknowledgement ("ok", "haan")."""
    return bool(_GREETING_WORDS.match(text or ""))


# "Tell me more" with nothing yet to continue. Not off-topic — which is what the
# classifier called it, so the reply was a refusal to discuss anything outside
# Ayurveda — but a continuation of a conversation that has not started. A table,
# not a model call: there is nothing to be creative about, and the language is
# already resolved by the time this is read.
_NOTHING_TO_CONTINUE = {
    "english": "Happy to — what would you like to know more about? Name a topic, or tell me what's troubling you and I'll build you a full plan.",
    "hinglish": "Zaroor — kis baare mein aur jaanna hai? Koi topic bataiye, ya apni problem likhiye aur main poora plan bana deta hoon.",
    "devanagari": "ज़रूर — किस बारे में और जानना चाहेंगे? कोई विषय बताइए, या अपनी समस्या लिखिए और मैं पूरा प्लान बना देता हूँ।",
}


def _last_real_topic(context: ConsultContext) -> str:
    """The most recent thing the user actually asked about.

    A continuation carries no topic of its own, and the knowledge path never
    writes `context.problem` — it builds a throwaway context for retrieval and
    discards it — so the topic has to be recovered from the chat history: the
    newest user line that is not itself a follow-up or a greeting.

    Deliberately derived rather than stored. `ConsultContext` is versioned and
    persisted in Convex on every assistant message, so a new field would strand
    every conversation saved before this change.
    """
    for turn in reversed(context.chat_history):
        if turn.role != "user":
            continue
        text = (turn.text or "").strip()
        if text and not is_followup_request(text) and not is_small_talk(text):
            return text
    return context.problem or ""


def _continuation_question(topic: str, already_said: str) -> str:
    """What to ask the knowledge writer for when the user says "tell me more".

    The "already covered" text is folded into the QUESTION rather than added as
    a new prompt field on purpose: `KNOWLEDGE_ANSWER_PROMPT` is rendered with
    `.format()`, and the two eval scripts render the same template by hand — a
    new placeholder has broken them twice.
    """
    if not already_said:
        return topic
    return (
        f"{topic}\n\n"
        "The reader has ALREADY been told the following, so do not repeat it. "
        "Add what it leaves out — further detail, causes, practical specifics, "
        "or examples. Do not restate any sentence from it.\n"
        "--- ALREADY COVERED ---\n"
        f"{already_said}"
    )


def _escalate(
    context: ConsultContext, reason: str = "", said: str = ""
) -> ConsultResult:
    """Stop the consultation and send them to a doctor.

    ⚠ `said` IS NOT OPTIONAL IN PRACTICE. This was the only exit in the file that
    never called `remember_chat`, so the sentence that triggered the escalation
    was erased from the transcript. Combined with phase="completed", which skips
    gathering, the NEXT turn walked straight into write_plan:

        turn 1  "ulti me khoon aa raha hai"   -> escalation, history empty
        turn 2  "theek hai, ab kya karu"      -> a full six-section wellness plan

    A haematemesis disclosure followed one turn later by a food chart, with no
    adversarial phrasing - just the client echoing back the context we gave it.
    The whole-transcript scan could never re-catch it because the transcript no
    longer contained it.

    Recording the exchange fixes both halves: the red flag stays in
    `safety_fragments`, so every later turn re-escalates on it.
    """
    context.phase = "completed"
    # THE RISK IS RECORDED AS STATE, not only as a sentence in the transcript.
    #
    # Three of the five call sites below pass no `said` at all, so the
    # transcript mechanism this docstring describes records nothing for them —
    # including `gathered.red_flag`, the model's own verdict, which is the one
    # that catches a red flag no keyword covers. Setting it here means every
    # escalation persists, whatever detected it and whatever was recorded.
    # Deliberately never cleared; see `ConsultContext.risk_level`.
    context.risk_level = "urgent"
    context.risk_reason = reason or context.risk_reason or "a red flag in this conversation"
    if said:
        context = ctx_state.remember_chat(context, said, safety.ESCALATION_MESSAGE)
    if reason:
        print(f"[consult] escalating: {reason}")
    return ConsultResult(
        kind="escalation",
        condition=context.condition,
        answer=safety.ESCALATION_MESSAGE,
        context=context,
    )


async def _attached_filenames(principal: dict | None) -> list[str]:
    """Filenames this signed-in user has indexed, for the router's FACTS block.

    Cheap: a metadata read on the local Chroma collection, no embedding call and
    no network - measured at 0.00s, unlike `user_documents.search`, which has to
    embed the query remotely first.

    Empty for anonymous callers, which is what makes the `document` intent
    unavailable to them: the prompt says the intent does not exist when the list
    is "none", so nobody can ask about a file they have not attached, and nobody
    can ask about somebody else's.
    """
    user_id = (principal or {}).get("user_id")
    if not user_id:
        return []
    try:
        from src import user_documents

        return await asyncio.to_thread(user_documents.list_documents, user_id)
    except Exception as error:  # noqa: BLE001 - never let this block routing
        print(f"[consult] could not list attachments: {error}")
        return []


async def _retrieve(
    context: ConsultContext,
    principal: dict | None,
    conversation_id: str | None = None,
    document_question: bool = False,
):
    """`document_question` is set when the user asked ABOUT their attachment.

    It reaches `UploadedReportsRetriever` through `extras` and drops the
    relevance floor for that one turn. Measured: "ya pdf kis bara ma ha" scores
    nothing against a cardiology report, because a question with no subject has
    no subject to be similar TO - so the floor filtered every chunk away and the
    model, handed nothing, correctly reported that no file was attached. Asking
    what a document says is the one case where similarity is the wrong tool.
    """
    pipeline = get_pipeline()
    results = await pipeline.run(
        RetrievalContext(
            extras={"document_question": True} if document_question else {},
            query=ctx_state.search_query(context),
            problem=context.problem,
            intake_summary=ctx_state.intake_summary(context),
            # "user_id", not "userId". The camelCase key is whatever the browser
            # sent; the snake_case one is written by server.py from the verified
            # JWT subject. Only the verified one may select private documents,
            # so reading the wrong key here would undo the whole auth change.
            user_id=(principal or {}).get("user_id"),
            # WHICH conversation this is, so long-term memory can leave it out.
            #
            # Memory fetches this user's EARLIER consultations. With nothing to
            # exclude it also returned the turns of the chat currently on screen,
            # so the model was handed its own transcript a second time under the
            # heading "Earlier consultations with this user" — it reads as the
            # user having said everything twice. `memory.py` has always forwarded
            # this to Convex as `excludeSessionId`; nothing ever filled it in.
            #
            # The `principal` fallback is kept for callers that already set it.
            session_id=conversation_id or (principal or {}).get("sessionId"),
            auth_token=(principal or {}).get("token"),
        )
    )
    return pipeline, results



def knowledge_for_prompt(pipeline, results, include_sentinel: bool = True) -> str:
    """The retrieved block, marked as UNGROUNDED when no reference material came back.

    `responder` decides whether to admit ignorance with `knowledge or NO_KNOWLEDGE`
    -- an EMPTINESS test. That was wrong, and silently so. `to_prompt_block`
    concatenates every non-empty retriever, and `PreviousConversationsRetriever`
    (order 20) is enabled for every signed-in user. So for anyone with history the
    block was never empty, `NO_KNOWLEDGE` never appeared, and the honesty branches
    in PLAN_PROMPT and KNOWLEDGE_ANSWER_PROMPT could not fire.

    What that produced: a full six-section health plan, on a question no reference
    note covers, grounded on the assistant's OWN recycled earlier answers -- sitting
    under a heading that grounding rule 9 calls "your FIRST source". A brand-new
    user got an honest refusal; a returning user got a confident invention. Exactly
    backwards.

    So the test is GROUNDING, not emptiness: did any retriever that actually holds
    Ayurveda reference material contribute?

    Reports (`report:`) and memory (`memory:`) deliberately do NOT count. The
    honesty sentence is a claim about the reference corpus, and rule 12 already
    gives a user's own uploaded report its own, higher authority. Their text is
    still passed through -- it is context the model should read -- it just no
    longer suppresses the admission.

    `include_sentinel=False` is for the ONE caller (the plan path in `run_turn`)
    that now decides groundedness PER SECTION via `consult.evidence.
    evaluate_sections`, using this same `results` list — the per-section
    `[Evidence: ...]` tags in `sections.render_section_spec` already carry that
    signal, so prepending this whole-block NO_KNOWLEDGE marker on top would just
    contradict a section the evidence map marked SUPPORTED. Every other caller
    (write_knowledge's continuation/document/general-question branches) keeps
    the default and is unaffected.
    """
    block = pipeline.to_prompt_block(results)
    grounded = any(
        chunk.source.startswith(("graphrag:", "knowledge:"))
        for result in results
        for chunk in result.chunks
    )
    if grounded or not include_sentinel:
        return block
    return f"{NO_KNOWLEDGE}\n\n{block}" if block else NO_KNOWLEDGE


async def _answer_knowledge_mid_consultation(
    context: ConsultContext,
    question: str,
    principal: dict | None,
    conversation_id: str | None,
    on_token: Callable[[str], None] | None = None,
    document_question: bool = False,
) -> ConsultResult:
    """Answer a general question WITHOUT disturbing the open consultation.

    The front-door knowledge branch cannot be reused here, because it ends with
    `context.phase = "casual"` — which would abandon a consultation the user is
    part-way through. Everything else is the same: a throwaway context is built
    for retrieval so the search runs on the QUESTION, and the real context is
    left holding its phase, condition, symptoms, round and help_type.

    THE ROUND IS DELIBERATELY NOT ADVANCED. `MAX_GATHERING_ROUNDS` counts how
    long we have been questioning this person; a question they asked US is not
    one of our rounds, and burning one would end the intake early for somebody
    who simply wanted to understand a word we used. This differs from the
    small-talk branch, which DOES count — "bas yahi hai" is an attempt to end
    the intake, so it has to move the counter or the intake never finishes.
    """
    question_context = ConsultContext(problem=question)
    pipeline, results = await _retrieve(
        question_context, principal, conversation_id, document_question=document_question
    )
    answer = await write_knowledge(
        question, knowledge_for_prompt(pipeline, results), context.language, on_token
    )
    context = ctx_state.remember_chat(context, question, answer)
    return ConsultResult(
        # `chat`, not `answer`: this is prose, not the sectioned plan, and
        # `looks_like_plan` decides how the client renders it.
        kind="answer" if looks_like_plan(answer) else "chat",
        condition=context.condition,
        message=answer,
        answer=answer,
        context=context,
        sources=pipeline.to_sources(results),
    )


async def run_turn(
    *,
    problem: str,
    raw_context: dict | None,
    answers: dict | None,
    free_text: str | None,
    profile: str = "",
    principal: dict | None = None,
    on_token: Callable[[str], None] | None = None,
    conversation_id: str | None = None,
) -> ConsultResult:
    """Advance the consultation by one turn.

    `on_token` is optional and purely additive. When supplied, prose answers hand
    their text over piece by piece as the model writes it; the ConsultResult that
    comes back is byte-for-byte what it would have been without it, so every
    caller, the stored transcript and the non-streaming endpoint are unaffected.

    Only prose is streamed. Intake question cards are structured JSON that the UI
    renders as a form — half of one is not a form — so those turns arrive whole
    exactly as before.
    """
    context = ctx_state.load_context(raw_context)
    message = (problem or "").strip()

    # THE PROFILE, LOADED ONCE PER CONVERSATION.
    #
    # Not per turn: the client round-trips this blob and Convex already
    # persists it (`consults.state`), so after the first load it rides along
    # for free. `profile_loaded` is a separate flag from "the profile is
    # empty" precisely so that a person with no stored profile does not cause
    # a Convex round trip on every single turn.
    #
    # Fails soft to an empty profile - no verified user, feature off, Convex
    # unconfigured, route not deployed yet. A backend running ahead of the
    # Convex side therefore behaves exactly as it did before, with the profile
    # confined to the live conversation.
    if not context.profile_loaded:
        context.patient_profile = await profile_store.load(
            (principal or {}).get("user_id")
        )
        context.profile_loaded = True

    # Nothing was actually sent. Without this the empty string fell straight past
    # the router into the planner, which then started a consultation about "".
    has_input = bool(message or answers or (free_text or "").strip())
    if not has_input and context.phase not in CONSULTING:
        return ConsultResult(kind="chat", message="", answer="", context=context)

    # --- front door -------------------------------------------------------
    # `problem` is only sent when the user typed outside an active consultation,
    # so this is where the conversation is steered  -  or a new consultation begins.
    # --- language memory ----------------------------------------------------
    # Resolved once per turn, before anything else looks at the text, and stored
    # on the context so every later step reads the same answer.
    #
    # Order matters: an explicit request wins, then whatever the conversation
    # already settled into, and only a first message falls back to detection.
    # Detecting per message was the bug  -  "tell me more" contains no Hindi
    # function words, so an English conversation flipped to Hinglish on the very
    # next turn purely because the follow-up looked English-free.
    spoken = message or (free_text or "")
    asked_for = requested_language(spoken)
    if asked_for:
        context.language = asked_for
    elif not context.language and len(spoken.split()) >= 3:
        # Short openers ("hi", "hello") carry no reliable signal; wait for a real
        # sentence rather than locking the conversation to a guess.
        context.language = detect_language(spoken)

    # Both input fields, resolved once: the urgent gate below and the
    # keyword scan under it each need to see whatever the user actually
    # typed, in whichever field it arrived.
    _typed_now = (free_text or "").strip()

    # ONCE URGENT, ALWAYS URGENT — for the rest of this conversation.
    #
    # Placed BEFORE the keyword scan below, deliberately. A conversation that
    # is already urgent does not need re-detecting — it needs answering. With
    # the gate after the scan, any red flag expressible as a keyword re-fired
    # `safety.scan` on every following turn (the transcript still holds it,
    # see state.safety_fragments) and returned the fixed ESCALATION_MESSAGE
    # forever, so "ulti me khoon" users never got the tailored reply at all —
    # measured, Hinglish and Devanagari follow-ups both came back canned.
    # The scan still runs for conversations not yet urgent, which is where it
    # matters: first detection escalates, every turn after is answered.
    # Past this point gathering, asking_focus,
    # retrieval, write_plan and write_knowledge are all unreachable, which is
    # what "safety takes priority over help_type, sections, retrieval, yoga,
    # remedies and diet" means in code rather than in a prompt.
    #
    # This is the fix for the case that started it: after escalating on
    # "vomiting 5+ times a day", the next turn "Can you tell me some yoga?"
    # skipped gathering (phase="completed"), matched no red-flag keyword, and
    # fell through to write_plan — which produced a full sectioned plan for
    # somebody who could not keep fluids down.
    #
    # The reply is generated so it can name what they actually asked for and
    # say why it should wait; it falls back to safety.ESCALATION_MESSAGE if
    # the model is unreachable, so this can never fail open.
    if context.risk_level == "urgent":
        asked_for = message or _typed_now
        print(f"[consult] safety-first reply (risk={context.risk_reason!r})")
        reply = await write_safety_first(
            problem=context.problem or context.condition,
            request=asked_for,
            reason=context.risk_reason,
            language=context.language,
        )
        context = ctx_state.remember_chat(context, asked_for, reply)
        # `escalation`, so the client keeps the warning styling it already
        # gives the first one. Nothing about the contract changes.
        return ConsultResult(
            kind="escalation",
            condition=context.condition,
            message=reply,
            answer=reply,
            context=context,
        )

    # ONE SCAN, ABOVE EVERYTHING, ON BOTH FIELDS.
    #
    # Two earlier attempts put this lower and both left holes. A red flag can
    # arrive as `problem`, as `freeText`, or as BOTH IN ONE REQUEST - and the
    # branches below (follow-up rework, small talk, aside, the fast path) all
    # answer and return before any per-field check further down. Measured:
    #
    #   problem="explain in english"  freeText="ulti me khoon aa raha hai"  -> answered
    #   problem="hii"                 freeText="khudkushi ka mann karta hai" -> answered
    #
    # `scan` takes varargs and skips empties, so one call covers every shape.
    if safety.scan(message, _typed_now, *ctx_state.safety_fragments(context)):
        # THE TRANSCRIPT IS SCANNED HERE TOO, not just this message.
        #
        # Recording the escalation (see `_escalate`) fixed a plan being written
        # one turn later, but it left a smaller hole: "aur batao" carries no red
        # flag of its own, so it fell through to the follow-up branch, which
        # reworded the escalation message and returned kind="chat". The words
        # stayed safe, but the client renders chat as ordinary prose - no
        # warning styling - and the conversation carried on as if nothing had
        # happened.
        #
        # Once somebody has said they are vomiting blood, every following turn
        # should keep pointing at a doctor. There is no wellness answer that
        # becomes appropriate again three messages later.
        return _escalate(context, "red-flag keyword", said=message or _typed_now)


    # A FOCUS REPLY CAN ARRIVE IN EITHER FIELD, and which one is not the
    # client's fault. docs/api-contract.md tells clients to send `problem`
    # whenever `phase` is outside CONSULTING, and `asking_focus` is
    # deliberately outside it (see schema.py) - so a CONTRACT-CONFORMANT
    # client sends the focus reply as `problem`, while every in-repo caller
    # (try_it.py, tests) happens to send `freeText`. That is why this survived
    # the test suite and broke in production.
    #
    # Left alone, the front door below routes it as a brand new message:
    # `route_message` returns `health`, the grounding guard downgrades it to
    # `knowledge` because the reply carries no symptom word (router.py, logged
    # as "health follow-up in an active conversation"), and it is answered from
    # a THROWAWAY ConsultContext(problem=message) - so retrieval searched for
    # "root cause and complete plan both" instead of the condition, the reply
    # was generic onboarding text ending "...describe any specific health
    # problems", `phase` was reset to "casual", and `help_type` stayed "".
    # Observed in production on an acidity consultation that had already
    # finished gathering.
    #
    # Normalising to `free_text` makes the `problem` shape take the EXACT path
    # the `freeText` shape already takes and is already tested on, rather than
    # adding a second branch that could drift from it. Deliberately after the
    # safety scan above, which reads both fields, so escalation is unchanged.
    if context.phase == "asking_focus" and message and not _typed_now:
        free_text, message = message, ""

    if message:

        # Follow-ups are checked BEFORE classification and before any retrieval.
        # "Explain this in English" is an instruction about the answer already on
        # screen, so re-running the classifier (which used to call it "casual")
        # or searching the knowledge base again would both answer the wrong
        # question. Handled here, in code, because the phrasings are a small
        # closed set and getting it wrong is glaringly visible.
        if is_followup_request(message):
            topic = _last_real_topic(context)
            continuing = is_continuation_request(message)

            if continuing and not topic and not context.last_answer:
                # "tell me more" as the very first message. There is nothing to
                # continue, which is not the same as being off-topic — but the
                # classifier had no way to tell the difference and refused.
                reworked = _NOTHING_TO_CONTINUE.get(
                    context.language or "hinglish", _NOTHING_TO_CONTINUE["hinglish"]
                )
            elif continuing and topic:
                # A request to ADD. `rework_answer` is told to introduce no new
                # facts, so it answered "tell me more" with the previous reply
                # word for word. Go back to the notes for the same topic, and
                # say what has already been covered so the model extends it.
                question_context = ConsultContext(problem=topic)
                pipeline, results = await _retrieve(question_context, principal, conversation_id)
                reworked = await write_knowledge(
                    _continuation_question(topic, context.last_answer),
                    knowledge_for_prompt(pipeline, results),
                    context.language,
                )
            elif context.last_answer:
                reworked = await rework_answer(
                    context.last_answer, message, context.language
                )
            elif context.problem:
                # A follow-up with nothing to rewrite, but a known topic. Happens
                # whenever the first turn opened question cards instead of
                # answering: "gas problem ho rahi hai" -> cards, then "explain
                # this in English" had no previous answer, fell through to the
                # classifier, and came back as the OFF-TOPIC refusal. Answer the
                # topic itself rather than pretending not to understand.
                question_context = ConsultContext(problem=context.problem)
                pipeline, results = await _retrieve(question_context, principal, conversation_id)
                reworked = await write_knowledge(
                    context.problem, knowledge_for_prompt(pipeline, results), context.language
                )
            else:
                reworked = ""

            if reworked:
                context = ctx_state.remember_chat(context, message, reworked)
                if context.phase not in ("completed", *CONSULTING):
                    context.phase = "casual"
                return ConsultResult(
                    # A reworked PLAN is still a plan. `FOLLOWUP_PROMPT` rule 6
                    # tells the model to keep the bold headings, and the client
                    # renders `chat` as one plain paragraph with no markdown - so
                    # returning this as chat printed literal `**Root Cause**`
                    # asterisks on screen for "explain this in English", the most
                    # common follow-up there is. Prose replies stay chat.
                    kind="answer" if looks_like_plan(reworked) else "chat",
                    message=reworked,
                    answer=reworked,
                    context=context,
                )


        # A question about a file they attached, from someone signed in.
        #
        # `knowledge` is the ONLY intent whose branch puts uploaded-report text in
        # front of a model (see `route.intent == "knowledge"` below, which passes
        # `principal` into `_retrieve`). The classifier has no intent for "what is
        # in my file" and cannot learn one reliably, so this is decided here.
        #
        # `has_health_signal` is the guard that keeps this narrow: "mujhe acidity
        # hai, meri report dekho" still opens a consultation, because it carries a
        # complaint. Only the bare document question is redirected.
        if (
            (principal or {}).get("user_id")
            and is_about_uploaded_document(message)
            and not has_health_signal(message)
        ):
            route = Route(intent="knowledge")
        # Fast path: the alias index already named a topic and the wording is a
        # question, not "mujhe X hai". That is exactly what the classifier would
        # answer, so asking it costs ~2.5s of the user's wait for a verdict we
        # already have. Deliberately narrow - anything ambiguous still goes to
        # the model.
        elif match_topics(message) and not is_personal_complaint(message):
            route = Route(intent="knowledge")
        else:
            route = await route_message(
                message,
                history=ctx_state.render_history(context),
                greeted=context.greeted,
                # Resolved just above, so an explicit "answer in Hindi from now
                # on" takes effect on THIS reply rather than the next one.
                language=context.language,
                # The filenames this person has attached, so the classifier can
                # resolve a REFERENCE to one. Without it "ya dusra wala kis bare
                # mein hai" is unplaceable - it names no document, it points at
                # one - and it was landing on `other`, the off-topic refusal.
                documents=", ".join(await _attached_filenames(principal)) or "",
            )

        if route.intent == "unavailable":
            # Couldn't reach the model. Report it as an ERROR rather than as
            # something the assistant said  -  the user needs to know to wait, not
            # to rephrase. The conversation is left exactly where it was (nothing
            # recorded, state machine untouched) so a retry resumes cleanly.
            return ConsultResult(
                kind="error", message=route.reply, answer=route.reply, context=context
            )

        if route.intent in CONVERSATIONAL:
            # Chit-chat, thanks, a goodbye, or "I don't actually need help".
            # Remember it, so the next reply follows on instead of restarting.
            context = ctx_state.remember_chat(context, message, route.reply)
            # `about` counts too. Both intents answer with "hello, here is what I
            # am", and only `greeting` used to set this — so a conversation that
            # opened with an introduction was still told "already greeted: no" on
            # the next turn, and the model gave the SAME self-introduction again.
            # Observed three times in a row, word for word, in one conversation.
            context.greeted = context.greeted or route.intent in ("greeting", "about")
            context.phase = "greeted" if route.intent == "greeting" else "casual"
            return ConsultResult(
                kind="chat", message=route.reply, answer=route.reply, context=context
            )

        if route.intent in ("knowledge", "document"):
            # One path, two intents. `document` differs only in that the answer
            # must come from the attachment even when the question is too vague
            # to match it - "what is this about" is similar to nothing in
            # particular, so the relevance floor would filter the whole file
            # away and the model would truthfully report that nothing was
            # attached. `document_question` drops that floor for this turn.
            #
            # The keyword check stays as a second source. The classifier is a
            # temperature-0.7 call and this is deterministic, so an obvious
            # phrasing ("is file me kya likha hai") does not depend on it.
            question_context = ConsultContext(problem=message)
            pipeline, results = await _retrieve(
                question_context,
                principal,
                conversation_id,
                document_question=(
                    route.intent == "document"
                    or is_about_uploaded_document(message)
                ),
            )
            answer = await write_knowledge(
                message, knowledge_for_prompt(pipeline, results), context.language, on_token
            )
            context = ctx_state.remember_chat(context, message, answer)
            context.phase = "casual"
            return ConsultResult(
                kind="chat",
                message=answer,
                answer=answer,
                context=context,
                sources=pipeline.to_sources(results),
            )

        # A real health concern: start the consultation, but keep the chat that
        # led here so the assistant doesn't greet them all over again.
        context = ConsultContext(
            problem=route.problem or message,
            phase="gathering",
            **ctx_state.carry_conversation(context),
        )
        context = ctx_state.remember_chat(context, message, "")

    if not context.problem:
        context.problem = message

    # --- typed text while a card set is open --------------------------------
    # The client sends `freeText` (not `problem`) once a consultation is running,
    # and this used to be filed as extra detail without ever being read. Observed
    # in a real session: with acidity cards on screen the user typed "i am facing
    # migraine pain since last night" and then "hii"  -  both were absorbed as
    # notes, the panel stayed titled "Acidity", and the greeting helped trigger
    # the final plan. So classify it first: a new complaint restarts, chit-chat
    # gets answered, and only genuine extra detail becomes a note.
    typed = (free_text or "").strip()

    # THE SAME SCAN ON THE freeText SIDE, and this is the one that mattered most.
    # Once a consultation opens the client stops sending `problem` and sends
    # `freeText`, so EVERY turn after the first arrives here - and the branches
    # below (follow-up rework, small talk, aside) all answer and return before
    # the whole-transcript scan further down ever runs. "khudkushi ka mann karta
    # hai, in short batao" matched a rework pattern and got a reworded wellness
    # answer. The rework patterns are unanchored, so any red flag with a
    # follow-up phrase anywhere in the sentence took this path.

    if typed and not answers and context.phase in CONSULTING and is_followup_request(typed):
        # A follow-up typed while cards are open. It must be handled here as well
        # as in the `message` branch above, because once a consultation starts the
        # client sends `freeText` instead of `problem` - so "explain this in
        # English" never reached the follow-up check, went to the classifier
        # instead, and came back as the OFF-TOPIC refusal.
        #
        # The continuation split applies here too: with cards open, "aur batao"
        # is still a request for more, and re-presenting the same answer is
        # still the wrong reply to it. The topic is known here — it is the
        # consultation's own problem — so there is no "nothing to continue" case.
        if is_continuation_request(typed):
            question_context = ConsultContext(problem=context.problem)
            pipeline, results = await _retrieve(question_context, principal, conversation_id)
            reworked = await write_knowledge(
                _continuation_question(context.problem, context.last_answer),
                knowledge_for_prompt(pipeline, results),
                context.language,
            )
        elif context.last_answer:
            reworked = await rework_answer(context.last_answer, typed, context.language)
        else:
            # Cards are open but nothing has been answered yet, so there is no
            # previous answer - explain the topic itself in the asked-for language.
            question_context = ConsultContext(problem=context.problem)
            pipeline, results = await _retrieve(question_context, principal, conversation_id)
            reworked = await write_knowledge(
                context.problem, knowledge_for_prompt(pipeline, results), context.language
            )
        context = ctx_state.remember_chat(context, typed, reworked)
        return ConsultResult(
            # Same reasoning as the follow-up branch above. Reachable with a
            # sectioned answer because this path also calls `write_knowledge`.
            kind="answer" if looks_like_plan(reworked) else "chat",
            condition=context.condition,
            message=reworked,
            answer=reworked,
            context=context,
        )

    if (
        typed
        and not answers
        and context.phase in CONSULTING
        and is_small_talk(typed)
        # ...but only while the intake has rounds left. This is the SECOND place
        # a conversational reply short-circuits the turn, and both had to learn
        # the same lesson: returning here forever means `gather` never runs, its
        # MAX_GATHERING_ROUNDS ceiling never fires, and the user is asked for
        # more detail until they give up. Traced live, "ok" and "haan" mixed into
        # a normal intake pinned it at round 4 through six turns with no plan.
        and context.round < MAX_GATHERING_ROUNDS
    ):
        # "hii" while a consultation is open. Settled in code, BEFORE the router,
        # so it cannot depend on a classification that might come back wrong - or
        # not come back at all when the model is unreachable.
        #
        # This is the screenshot bug: the greeting fell through to `add_note`,
        # was filed as a symptom, and advanced the questionnaire, so saying hello
        # produced "Almost done - what would you like me to cover?".
        #
        # No model call, so this also works when the LLM is down. The cards are
        # left standing exactly as they were.
        reply = SMALL_TALK_REPLIES.get(
            "greeting" if _looks_like_greeting(typed) else "ack"
        )
        # Counts towards the ceiling. Someone answering "ok" is still spending a
        # turn of the intake, and pretending otherwise is what made it endless.
        context.round += 1
        context = ctx_state.remember_chat(context, typed, reply)
        return ConsultResult(
            kind="chat",
            condition=context.condition,
            message=reply,
            answer=reply,
            context=context,
        )

    if typed and not answers and context.phase in CONSULTING:
        # The open consultation is stated explicitly. Chat history alone was not
        # enough: asked "main aapko kya bata raha tha?" three turns into an
        # insomnia intake, the router replied "Arre, kuch khaas nahi"  -  it could
        # not see that a consultation was in progress, so an aside made the
        # assistant look like it had forgotten the whole conversation.
        open_case = f"(An open consultation about: {context.problem})"
        aside = await route_message(
            typed,
            history=f"{open_case}\n{ctx_state.render_history(context)}",
            greeted=context.greeted,
            language=context.language,
        )
        if aside.intent == "unavailable":
            return ConsultResult(
                kind="error", message=aside.reply, answer=aside.reply, context=context
            )

        if (
            aside.intent == "health"
            and has_health_signal(typed)
            and is_personal_complaint(typed)
        ):
            # A different problem entirely. Starting fresh beats appending it to a
            # consultation about something else, which produced a plan for the old
            # condition carrying the new one's details.
            context = ConsultContext(
                problem=aside.problem or typed,
                phase="gathering",
                **ctx_state.carry_conversation(context),
            )
            context = ctx_state.remember_chat(context, typed, "")
            free_text = None
        elif aside.intent in ("knowledge", "document") and not aside.health_followup:
            # A REAL QUESTION, ASKED MID-INTAKE. Answer it.
            #
            # `health_followup` is what keeps this from swallowing the intake.
            # The router downgrades a health verdict to `knowledge` when the
            # message carries no symptom word but the conversation is already
            # about health — which is exactly what an ANSWER to a gathering
            # question looks like ("bas itna hi hai", "2 din se"). Diverting
            # those here stalled the intake completely: measured, five
            # consecutive answers all came back as knowledge replies and the
            # consultation never left `gathering`. See router.Route.
            #
            # This branch did not exist, and `knowledge` is not in
            # CONVERSATIONAL, so the question fell through to `add_note` and
            # `gather` below — it was filed as a symptom and answered with the
            # NEXT INTAKE QUESTION. Reproduced live against production:
            # "Tell me something about Ayurveda", asked during a gathering
            # phase, came back "I understand. To get a clearer picture of your
            # digestion, could you tell me if you are experiencing any changes
            # in your bowel movements...". The user asked what Ayurveda is and
            # was interrogated about their bowels.
            #
            # Not routed back through the front door on purpose: that path ends
            # by setting phase="casual", which would silently abandon the
            # consultation. The helper answers and leaves every piece of state
            # exactly where it was, so the next turn carries on gathering.
            return await _answer_knowledge_mid_consultation(
                context,
                typed,
                principal,
                conversation_id,
                on_token,
                document_question=(
                    aside.intent == "document" or is_about_uploaded_document(typed)
                ),
            )
        elif aside.intent in CONVERSATIONAL and context.round < MAX_GATHERING_ROUNDS:
            # "hii", "thanks", "haan"  -  answer it and leave the intake standing,
            # but ONLY while the intake still has rounds left. At the ceiling this
            # branch stops catching the turn and it falls through to `gather`,
            # which sees `rounds >= MAX_GATHERING_ROUNDS` and writes the plan.
            #
            # Returning here unconditionally was a dead end, and counting the
            # round was not enough to fix it: the counter rose to 7 while the
            # ceiling that reads it lives inside `gather`, which this branch
            # returns before ever reaching.
            # Filing these as symptoms is what let a greeting push the intake on.
            #
            # It still COUNTS, though, and not counting it was a dead end. This
            # branch returns before `gather` runs, so `context.round` never moved
            # and `MAX_GATHERING_ROUNDS` could never fire. Traced live: someone
            # who answers "bas yahi hai" - "that's all" - is asked again, and
            # again, and never receives a plan:
            #
            #     "mujhe gas ho rahi hai"  -> question, round 1
            #     "bas yahi hai"  x7       -> question, round 1, seven times
            #
            # That is the single most natural way to say "I am done talking", so
            # the intake has to end somewhere. Counting it is the same trade
            # gathering.MAX_GATHERING_ROUNDS already makes: an assistant that
            # keeps asking forever is worse than one that answers with slightly
            # less detail.
            # ...but a QUESTION they asked is not one of our rounds.
            #
            # The counter exists to stop "bas yahi hai" x7 pinning the intake
            # forever — an attempt to end the conversation without answering.
            # Someone asking what Ayurveda is, or what this assistant does, is
            # doing the opposite, and charging them an intake round for it
            # means a curious person gets a thinner consultation.
            #
            # This surfaced when the transcript started carrying the user's
            # gathering answers (see the `remember_chat` fix below): with more
            # health context in the history, the router began classifying
            # "Tell me something about Ayurveda" as `about` rather than
            # `knowledge`, so it landed here instead of in the knowledge
            # branch above and quietly started costing a round.
            if aside.intent not in ("about", "other"):
                context.round += 1
            context = ctx_state.remember_chat(context, typed, aside.reply)
            return ConsultResult(
                kind="chat",
                condition=context.condition,
                message=aside.reply,
                answer=aside.reply,
                context=context,
            )

    context, _ = ctx_state.resolve_answers(context, answers)
    context = ctx_state.add_note(context, free_text)

    # --- serious diagnosed condition ---------------------------------------
    # Checked before the intake planner runs, so a cancer or dialysis disclosure
    # never becomes a five-card questionnaire and a food chart. Not an
    # escalation either - "go to hospital now" is the wrong answer to someone
    # who has been living with this for a year.
    # Scanned over everything the USER has said, not just `context.problem`.
    # A diagnosis disclosed three turns in ("actually I'm on dialysis") was
    # missed entirely, because `problem` only ever holds the opening sentence.
    # Deliberately `user_fragments`, not `safety_fragments`: the latter
    # includes the assistant's own turns, and this matches bare condition
    # names the assistant says routinely when explaining when to see a doctor.
    _serious = next(
        (f for f in ctx_state.user_fragments(context) if safety.is_serious_condition(f)),
        "",
    )
    if _serious and not context.serious_condition:
        # RECORDED ONCE, THEN THE CONVERSATION CONTINUES.
        #
        # This used to jump straight to `write_supportive_care` with
        # phase="completed". Because `_serious` is re-derived from the
        # transcript every turn, the branch then re-fired forever: the user
        # answered "AML, chemotherapy chal rahi hai" and received the same
        # supportive-care paragraph again. Nothing about the diagnosis was
        # ever collected, so nothing reached the profile, the safety checks or
        # the final answer.
        #
        # Holding it on the context turns it into a clinical deep-dive
        # instead: `gather()` runs in SERIOUS_CONDITION_MODE, asking what type
        # it is, what treatment is running and what is troubling them most,
        # one or two questions at a time — and is forbidden from offering a
        # remedy while it does. `write_supportive_care` still writes the
        # guidance, but below, once there is something real to write it from.
        context.serious_condition = _serious
        print(f"[consult] serious condition disclosed: {_serious[:60]!r}")

    # --- safety, over the WHOLE conversation ------------------------------
    # Widened deliberately. The planner's per-option `red_flag` markers were the
    # PRIMARY defence and went with the cards, so the keyword scan — which
    # safety.py itself describes as the backstop — now reads the entire
    # transcript rather than just the opening complaint. "I have acidity" is
    # harmless; "there was blood in it this morning", three turns later, is not.
    flagged = ctx_state.selected_red_flags(context)  # legacy card contexts only
    if flagged:
        return _escalate(context, f"planner-marked option: {flagged[0]}")
    if safety.scan(*ctx_state.safety_fragments(context)):
        return _escalate(context, "red-flag keyword")

    # THE GRADED VERDICT, computed here and used far below by the recommendation
    # gate. Deliberately BEFORE retrieval and before the plan is written, so
    # nothing GraphRAG returns can raise the ceiling on what may be offered.
    #
    # `_escalate` above still owns RED — this does not replace the emergency
    # path, it adds the two rungs between "emergency" and "ordinary" that the
    # boolean never had. See clinical/triage.py.
    _triage = clinical_triage.assess(
        ctx_state.user_fragments(context),
        profile_conditions=context.patient_profile.active("conditions"),
        profile_medications=context.patient_profile.active("medications"),
        serious_condition=context.serious_condition,
    )
    if _triage.risk_level != "GREEN":
        print(f"[triage] {_triage.risk_level}: {_triage.reason[:110]}")

    # --- 1. gather, in prose ----------------------------------------------
    # Replaces the question cards. This is a conversation, not a form, and the
    # user is never asked to pick from a list to answer an intake question.
    #
    # `asking_focus` is deliberately excluded here too, alongside `completed`
    # — it has already gathered enough and is waiting on a DIFFERENT question
    # (which sections they want), not another intake round.
    if context.phase not in ("completed", "asking_focus"):
        # THE CURRENT MESSAGE GOES INTO THE TRANSCRIPT BEFORE IT IS ANSWERED.
        #
        # It used to be recorded only after `gather` had already run, so every
        # prompt built in this turn read a history that stopped at the previous
        # question — the answer being responded to was missing from it. The
        # model, seeing its question and no reply, asked the same thing again.
        #
        # This one line is also what puts the user's last gathering answer into
        # the transcript that `write_supportive_care` and the final plan read
        # further down: those paths record only the assistant's side, so the
        # message that ENDED the intake was previously dropped entirely.
        #
        # Idempotent — see `state.remember_user_message` for why the restart
        # branch above makes that necessary.
        context = ctx_state.remember_user_message(context, typed)

        gathered = await gather(
            problem=context.problem,
            history=ctx_state.render_history(context),
            symptoms=context.symptoms,
            # Last turn's own list of gaps, so the next question follows on
            # instead of wandering. Populated every turn, never read until now.
            missing_info=context.missing_info,
            # What is already known, as prose. NOT a list of unfilled fields —
            # see state.render_profile for why a queue would make this a form.
            profile=ctx_state.render_profile(context.patient_profile),
            # Non-empty turns this into the clinical deep-dive described in
            # prompts.SERIOUS_CONDITION_MODE.
            serious_condition=context.serious_condition,
            # The conversation's sticky language, resolved above from what the
            # user actually typed. `context.problem` is the router's Latin
            # restatement, so this must not be re-detected from it.
            language=context.language,
            rounds=context.round,
        )

        context.condition = gathered.condition or context.condition
        context.symptoms = ctx_state._merge_symptoms(context.symptoms, gathered.symptoms)
        context.missing_info = gathered.missing_info

        # WHICH PROBLEM IS THIS? Deterministic, and it runs once the condition
        # is known so the match has a real name to work with rather than the
        # opening sentence. `problem`/`condition` stay exactly what they were —
        # the active episode's view of itself — so every existing reader is
        # untouched; the episode list is what lets a SECOND problem exist at
        # the same time and survive a topic switch. See clinical/episodes.py.
        # `spoken` (what they said THIS turn), not `context.problem`, which
        # holds the opening sentence for the life of the consultation. Matching
        # on the opener means every later turn still carries "acidity" into the
        # match, so "ab mere ghutne me bhi dard hai" scored against the acidity
        # episode and the knee never got one of its own. Falls back to the
        # opener for the first turn, where they are the same thing.
        context.episodes, _active, _is_new = clinical_episodes.select(
            context.episodes, spoken or context.problem, context.condition
        )
        context.active_episode_id = _active.episode_id
        if _is_new:
            print(f"[consult] new episode: {_active.problem_name!r}")
        # What has been learned about THIS problem lives on the episode, so it
        # is still there after the conversation has moved on and come back.
        _active.important_unknowns = list(context.missing_info)
        for _symptom in context.symptoms:
            if _symptom not in _active.associated_symptoms:
                _active.associated_symptoms.append(_symptom)
        del _active.associated_symptoms[:-12]

        # Long-term facts they stated this turn. `merge_profile` decides what
        # actually changed — scalars replace, lists merge, nothing is ever
        # dropped for going unmentioned — and the save is skipped entirely
        # when nothing did, which is the normal case.

        # NOTHING ABOUT A PERSON IS LEARNED FROM A QUESTION ABOUT A TOPIC.
        #
        # "Kidney disease mein kaunsi herb lo?" names a disease, and the model
        # duly reported `conditions: ["kidney disease"]` — for somebody who had
        # simply asked a general question. Found in the live browser and then
        # in the stored row: an account whose only mention of kidneys was that
        # question came away with kidney disease on its permanent profile.
        #
        # That is the one thing the profile must never hold. It is not a
        # transcript, it is the clinical background every FUTURE consultation
        # is shaped by — which herbs get avoided, which questions get asked,
        # what the final plan warns about. A wrong chronic condition there is
        # durable and invisible, and the person never said it.
        #
        # `is_personal_complaint` already draws exactly this line and was
        # simply never consulted here: it is False for "kidney disease mein
        # kaunsi herb lo" and True for "haan diabetes hai", including the bare
        # answers to gathering questions that carry no "mujhe" at all.
        #
        # A MISSED FACT IS RECOVERABLE AND A FABRICATED ONE IS NOT. If this
        # drops something real ("diabetes hai, kya khana chahiye?" reads as a
        # question), the statement is still in the transcript and the very next
        # turn can pick it up. The opposite error cannot be undone by anything
        # the user says, because they have no idea it happened.
        #
        # `spoken`, not `typed`: on the opening turn the message arrives as
        # `problem` and `typed` is empty.
        if gathered.profile_facts and not is_personal_complaint(spoken):
            print(
                "[consult] not recording profile facts from a general question: "
                f"{spoken[:60]!r} -> {gathered.profile_facts}"
            )
            gathered.profile_facts = {}

        # `profile_removals` is what makes "maine metformin band kar diya"
        # take effect. `merge_profile` has always accepted removals and
        # nothing ever passed any, so a stopped medicine stayed on the profile
        # for good — every later turn, and every later consultation, went on
        # shaping its advice around a drug the person no longer takes.
        # Deliberately still `or` and not `and`: a turn that only retracts
        # something must save just as surely as one that adds.
        if gathered.profile_facts or gathered.profile_removals:
            context.patient_profile, profile_changed = ctx_state.merge_profile(
                context.patient_profile,
                gathered.profile_facts,
                removals=gathered.profile_removals,
            )
            if profile_changed:
                await profile_store.save(
                    (principal or {}).get("user_id"), context.patient_profile
                )

        # The second of the three replacements for the planner's red flags: the
        # model reading the conversation and saying so outright.
        #
        # A DIAGNOSED CONDITION IS NOT AN EMERGENCY, and the model conflates
        # the two. safety.py keeps `scan` and `is_serious_condition` on
        # separate tracks on purpose — "these are NOT emergencies, someone
        # living with cancer for a year does not need 'go to hospital now'" —
        # but `red_flag` fires on the word cancer anyway. Measured: "mujhe
        # cancer ho gaya hai" escalated to sticky-urgent on the spot, so the
        # clinical deep-dive below could never run and every later turn came
        # back as a safety reply instead of a follow-up question.
        #
        # So the model's verdict is not honoured for a disclosure that the
        # serious-condition track has already claimed AND that carries no
        # emergency keyword of its own. "I have cancer" runs the deep-dive;
        # "I have cancer and I'm vomiting blood" still escalates, because
        # `safety.scan` catches the second half — as does any red flag raised
        # later in the deep-dive.
        if gathered.red_flag:
            _emergency = safety.scan(*ctx_state.safety_fragments(context))
            if not context.serious_condition or _emergency:
                return _escalate(context, "gathering flagged a red flag")
            print(
                "[consult] gathering flagged a red flag, but this is a "
                "disclosed serious condition with no emergency keyword — "
                "continuing the clinical deep-dive rather than escalating"
            )

        # WHEN THEY ASK FOR IT OUTRIGHT, THE QUESTIONS ARE OVER.
        #
        # Placed here on purpose: strictly BELOW the red-flag check above, so
        # "chest me dard ho raha hai, koi upay batao" still escalates and never
        # reaches a plan, and strictly ABOVE `ready`, so it can end an intake
        # the model wanted to continue.
        #
        # GATHERING_PROMPT already carries the rule ("true — they ask you to
        # just give the advice") and the model does not reliably follow it.
        # Reproduced in the live browser and again against `run_turn`: after
        # three rounds about acidity, "poora plan batao" came back as two more
        # questions — and they were the SAME two the previous turn had already
        # asked, about sleep and bowels. See router.asks_for_guidance_now.
        asked_outright = bool(typed) and asks_for_guidance_now(typed)
        if asked_outright and not gathered.ready:
            print(f"[consult] asked for guidance outright: {typed[:60]!r} — ending intake")
            gathered.ready = True

        if not gathered.ready:
            context.phase = "gathering"
            context.round += 1
            # THE ASSISTANT'S SIDE ONLY — the user's is already recorded.
            #
            # `remember_user_message` put the current message into the
            # transcript before `gather` ran, so passing `typed` here as well
            # would store it twice and read back as if they had repeated
            # themselves.
            #
            # Recording the answer only at this point is what caused the
            # duplicate questions: whatever the user said reached the
            # transcript one full turn late, so `gather` saw its own question
            # and no reply and asked the same thing again. Measured on the
            # serious-condition deep-dive: "blood cancer hai" and "AML hai,
            # chemotherapy chal rahi hai" were both answered and the next
            # question came back byte-for-byte identical. This is very likely
            # also the long-standing duplicate-question flake in
            # tests/test_intake.py.
            context = ctx_state.remember_chat(context, "", gathered.reply)
            return ConsultResult(
                kind="chat",
                condition=context.condition,
                message=gathered.reply,
                answer=gathered.reply,
                context=context,
            )

        # A SERIOUS CONDITION NEVER REACHES THE PLAN PATH.
        #
        # Once the deep-dive has what it needs, the guidance is written by
        # `write_supportive_care` — never by `write_plan`, so the six-section
        # wellness plan remains impossible for a diagnosed serious condition.
        # That guarantee predates this change and is not relaxed by it; what
        # changed is only that the supportive reply is now built from the type,
        # the treatment and the symptoms actually collected, instead of from
        # the single sentence that first mentioned the diagnosis.
        if context.serious_condition:
            context.phase = "completed"
            collected = "\n".join(
                part
                for part in (
                    f"They have told you they have: {context.serious_condition}",
                    ctx_state.render_profile(context.patient_profile),
                    ctx_state.render_history(context),
                )
                if part
            )
            reply = await write_supportive_care(collected, context.language)
            context = ctx_state.remember_chat(context, "", reply)
            return ConsultResult(
                kind="chat",
                condition=context.condition,
                message=reply,
                answer=reply,
                context=context,
            )

        # THEY MAY HAVE ALREADY ANSWERED THE FOCUS QUESTION.
        #
        # "poora plan batao" is both the reason the intake stopped and the
        # answer to "which part would you like?". Asking it back at somebody
        # who has just said `poora plan` is the questionnaire feel this whole
        # flow exists to remove, so the same sentence is read for a focus and,
        # when it names one, the plan is written this turn instead.
        #
        # `["complete"]` when it names nothing in particular ("bas ab batao",
        # "no more questions"): they asked to stop being questioned, and the
        # full plan is the honest reading of that. Falling back to the focus
        # question here would ask one more question of somebody who just said
        # they did not want any.
        if asked_outright:
            context.help_types = await classify_focus(typed, context.language) or ["complete"]
            context.help_type = (
                "complete" if "complete" in context.help_types else context.help_types[0]
            )
            context.phase = "completed"
            print(f"[consult] focus taken from the same message: {context.help_types}")
            # Deliberately NOT returning — falls through to the plan below.
        else:
            # ready -> the intake QUESTIONS are done, but retrieval and the plan
            # are not next yet. Ask what kind of help they want, conversationally
            # (no menu — see _FOCUS_QUESTION), and wait for that reply before
            # GraphRAG is ever reached.
            context.phase = "asking_focus"
            focus_question = _FOCUS_QUESTION.get(
                context.language, _FOCUS_QUESTION["hinglish"]
            ).format(condition=context.condition or "isse")
            context = ctx_state.remember_chat(context, "", focus_question)
            return ConsultResult(
                kind="chat",
                condition=context.condition,
                message=focus_question,
                answer=focus_question,
                context=context,
            )

    # --- 1b. which sections they want, from their reply to the focus question
    if context.phase == "asking_focus":
        spoken_focus = typed or message
        chosen_focus = await classify_focus(spoken_focus, context.language)

        if not chosen_focus:
            # NOT A FOCUS SELECTION. They asked something else instead of
            # choosing — a question of their own, an aside, small talk.
            #
            # This used to be impossible to see: `classify_focus` collapsed
            # every non-answer to ["complete"], so "Tell me something about
            # Ayurveda", typed at the focus question, wrote a full
            # six-section acidity plan. Reproduced live against production
            # before this fix (3,446 characters of plan in reply to a
            # general question).
            #
            # Answer what they actually said, and STAY in `asking_focus` so
            # the choice is still open. Nothing about the consultation is
            # reset: condition, symptoms and round all stand.
            aside = await route_message(
                spoken_focus,
                history=(
                    f"(An open consultation about: {context.problem}. They have "
                    "just been asked which part of the plan they want.)\n"
                    f"{ctx_state.render_history(context)}"
                ),
                greeted=context.greeted,
                language=context.language,
            )
            if aside.intent == "unavailable":
                return ConsultResult(
                    kind="error", message=aside.reply, answer=aside.reply, context=context
                )
            if aside.intent in ("knowledge", "document") and not aside.health_followup:
                result = await _answer_knowledge_mid_consultation(
                    context,
                    spoken_focus,
                    principal,
                    conversation_id,
                    on_token,
                    document_question=(
                        aside.intent == "document"
                        or is_about_uploaded_document(spoken_focus)
                    ),
                )
                # Re-ask, so the conversation does not stall waiting on a
                # choice the user has stopped being prompted for.
                nudge = _FOCUS_QUESTION.get(
                    context.language, _FOCUS_QUESTION["hinglish"]
                ).format(condition=context.condition or "isse")
                combined = f"{result.answer}\n\n{nudge}"
                result.context.phase = "asking_focus"
                return ConsultResult(
                    kind="chat",
                    condition=context.condition,
                    message=combined,
                    answer=combined,
                    context=result.context,
                    sources=result.sources,
                )
            # Anything else (small talk, a refusal, an off-topic remark):
            # reply if the router wrote one, then put the question back.
            nudge = _FOCUS_QUESTION.get(
                context.language, _FOCUS_QUESTION["hinglish"]
            ).format(condition=context.condition or "isse")
            reply = f"{aside.reply}\n\n{nudge}" if aside.reply else nudge
            context = ctx_state.remember_chat(context, spoken_focus, reply)
            context.phase = "asking_focus"
            return ConsultResult(
                kind="chat",
                condition=context.condition,
                message=reply,
                answer=reply,
                context=context,
            )

        context.help_types = chosen_focus
        # `help_type` (singular) stays populated for backward compatibility —
        # see schema.py for why widening it in place would reset in-flight
        # conversations. "complete" wins when present, since it is a superset
        # of everything else; otherwise the first choice represents the turn.
        context.help_type = (
            "complete" if "complete" in context.help_types else context.help_types[0]
        )
        # Entering the plan-writing branch this same turn — matches the
        # existing convention that "completed" means a plan is (about to be)
        # on screen, not literally that this exact turn already wrote one.
        context.phase = "completed"
        # falls through to "the plan" below, now scoped by help_type

    # --- 2. the plan -------------------------------------------------------
    # Which sections to write: the conversational focus choice takes
    # priority; `chosen.options` is kept only as a fallback for a context
    # persisted mid-flow through the retired card-based "choosing" step.
    # `resolve_sections(None)` -> DEFAULT_SECTIONS, so ALWAYS_INCLUDED —
    # "When To See A Doctor" — can never be dropped either way.
    chosen = context.answers.get(SECTIONS_QUESTION_ID)
    # `help_types` is authoritative; `help_type` is the backward-compatible
    # single value, read only for a context persisted before `help_types`
    # existed. See schema.py.
    help_types = context.help_types or (
        [context.help_type] if context.help_type else []
    )
    sections = resolve_sections(
        _sections_for(help_types) or (chosen.options if chosen else None)
    )

    pipeline, results = await _retrieve(context, principal, conversation_id)

    # A red flag or a serious condition can arrive in an uploaded report
    # rather than in what the user typed - somebody attaches a report
    # mentioning "blood in stool" or an oncology summary and asks a plain
    # question. The typed-disclosure checks above never see retrieved text
    # (they run before retrieval), so scan it here too, before it reaches
    # write_plan. Same principle `safety.scan`'s docstring already states for
    # the transcript: keyword matching over untrusted text is a backstop, and
    # it has to cover every channel that reaches the model, not just typing.
    report_text = " ".join(
        chunk.text
        for result in results
        for chunk in result.chunks
        if chunk.source.startswith("report:")
    )
    if report_text and safety.scan(report_text):
        # `said` is recorded (not the raw report text — just a marker) so the
        # escalation itself survives into `chat_history`/`safety_fragments`,
        # the same durability `_escalate`'s docstring requires for a typed
        # disclosure. Without this, a later turn whose retrieval happens not
        # to re-surface this exact chunk could silently un-escalate.
        return _escalate(
            context,
            "red-flag keyword in an uploaded report",
            said="(an attached report mentions something serious)",
        )
    if report_text and safety.is_serious_condition(report_text):
        context.phase = "completed"
        print("[consult] serious condition found in an uploaded report")
        reply = await write_supportive_care(
            f"{context.problem}\n\n(From their uploaded report: {report_text[:600]})",
            context.language,
        )
        context = ctx_state.remember_chat(context, "", reply)
        return ConsultResult(
            kind="chat",
            condition=context.condition,
            message=reply,
            answer=reply,
            context=context,
        )

    # What the plan is written FROM. This used to be `intake_summary` — the
    # "Question: Answer" lines from the cards. With the cards gone, the same
    # information now comes out of the conversation: the transcript is what the
    # user actually said, and `symptoms` is what the gathering step understood
    # from it.
    #
    # The transcript is safe HERE, unlike in `search_query`. This is prose going
    # to a language model that reads prose; that one is an embedding lookup where
    # conversational filler measurably destroys relevance.
    #
    # SECTION-LEVEL EVIDENCE EVALUATION. Which of the requested `sections`
    # have real (priority 1: knowledge:, priority 2: graphrag:<file>)
    # material behind them — reading the SAME `results` this turn already
    # retrieved, no extra call. See consult/evidence.py for the hierarchy and
    # why this replaced one whole-plan grounded/ungrounded flag: retrieval
    # already truncates per note (VECTOR_TOP_K=4 against ~7 chunks/note), so
    # a "complete" plan routinely has evidence for some sections and not
    # others even when the note is correctly matched.
    section_evidence = evidence.evaluate_sections(sections, results)

    # A LOCAL LLM WRITES THE PLAN, from whatever the Context Builder assembled
    # above — GraphRAG's retrieved passages/relationships, the local knowledge
    # fallback, memory, and uploaded reports, all already labeled by
    # `knowledge_for_prompt`. `safety.scan` and the gathering red-flag check
    # both run above this, and a flagged turn returns long before reaching here.
    details = "\n".join(
        part for part in (ctx_state.render_history(context), ", ".join(context.symptoms)) if part
    )
    # The profile joins whatever the caller sent. `write_plan` has always
    # taken a `profile` string that lands in PLAN_PROMPT's USER PROFILE block,
    # so history reaches the final answer through plumbing that already
    # existed. Rules 15 and 16 govern how it may be used: silently, only when
    # it changes the advice, and never recited back.
    _known = ctx_state.render_profile(context.patient_profile)
    profile = f"{profile}\n\n{_known}".strip() if profile else _known

    # WHAT KIND OF EVIDENCE IS BEHIND THIS, in one line the model must obey.
    #
    # A sentence from the Caraka Samhita and a randomised trial arrive as the
    # same shape — text plus a filename — and are indistinguishable to a model
    # that is handed both. That is how "research shows" ends up over a
    # classical description, which is the single most damaging thing this
    # product can say. `clinical/evidence_class.py` grades the sources and
    # returns the strongest wording the material actually supports.
    _classes = clinical_evidence.classify_chunks(
        [chunk for result in results for chunk in result.chunks]
    )
    _evidence_line = clinical_evidence.describe(_classes)

    answer = await write_plan(
        # `include_sentinel=False`: the per-section evidence tags above are
        # now what tells the model which parts are grounded, so the old
        # whole-block "no relevant notes found" marker would only contradict
        # a section that IS supported and hand the model words rule 14 now
        # forbids saying. See knowledge_for_prompt's docstring.
        # The evidence-grade line rides at the TOP of the knowledge block
        # rather than in a new parameter: `write_plan`'s signature is shared
        # with the legacy callers, and this is material about the material,
        # which is where the model already reads its sources from.
        knowledge=(
            _evidence_line
            + "\n\n"
            + knowledge_for_prompt(pipeline, results, include_sentinel=False)
        ),
        profile=profile,
        details=details,
        sections=sections,
        language=context.language,
        section_evidence=section_evidence,
    )

    # THE RECOMMENDATION GATE. Everything above this line PROPOSES; this is the
    # only thing that disposes. It runs on the generated text, deterministically:
    #
    #   - keeps only the sections that were actually asked for. "sirf yoga
    #     batao" returning the whole six-section plan was measured at roughly
    #     one turn in three once retrieval got richer, and no amount of prompt
    #     wording made it reliable;
    #   - removes any intervention that is unsafe for THIS person, checked
    #     against their ACTIVE medicines and conditions — `active(...)`, so a
    #     drug they stopped never drives a warning;
    #   - says plainly that something was left out, rather than silently
    #     thinning the advice.
    #
    # See clinical/gate.py. `_triage` was computed before retrieval, so a
    # GraphRAG passage cannot raise the ceiling it sets.
    _gate = clinical_gate.screen(
        answer,
        risk_level=(_triage.risk_level if _triage else "GREEN"),
        wanted_sections=sections,
        medications=context.patient_profile.active("medications"),
        conditions=context.patient_profile.active("conditions"),
        allergies=context.patient_profile.active("allergies"),
        language=context.language or "hinglish",
    )
    if _gate.dropped_sections or _gate.blocked_interventions or _gate.notes:
        print(f"[gate] {_gate.as_dict()}")
    if _gate.approved and _gate.answer.strip():
        answer = _gate.answer

    context.phase = "completed"
    # Remember the plan too, so "explain this in English" works on it just as it
    # does on a general answer.
    context = ctx_state.remember_chat(context, "", answer)
    sources = pipeline.to_sources(results)
    return ConsultResult(
        kind="answer",
        condition=context.condition,
        answer=answer,
        context=context,
        sources=sources,
    )
