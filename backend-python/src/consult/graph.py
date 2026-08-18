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
                                   retrieve -> plan (all sections)

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
routing we need. The old `src/graph.py` is untouched - `/chat` and `/jobs/run`
still depend on it.
"""

from __future__ import annotations

import re
from typing import Callable

import config
from src import safety
from src.consult import state as ctx_state
from src.consult.gathering import gather
from src.consult.responder import (
    NO_KNOWLEDGE,
    rework_answer,
    write_knowledge,
    write_plan,
    write_supportive_care,
)
from src.knowledge import match_topics
from src.consult.router import (
    CONVERSATIONAL,
    Route,
    detect_language,
    has_health_signal,
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
    "greeting": "Namaste! 🌿 Upar wale sawaalon ka jawab de dijiye, phir main aapke liye plan bana deta hoon.",
    "ack": "Theek hai 🙂 Jab taiyaar hon, upar ke sawaal chun lijiye.",
}

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


def _escalate(context: ConsultContext, reason: str = "") -> ConsultResult:
    context.phase = "completed"
    if reason:
        print(f"[consult] escalating: {reason}")
    return ConsultResult(
        kind="escalation",
        condition=context.condition,
        answer=safety.ESCALATION_MESSAGE,
        context=context,
    )


async def _retrieve(
    context: ConsultContext,
    principal: dict | None,
    conversation_id: str | None = None,
):
    pipeline = get_pipeline()
    results = await pipeline.run(
        RetrievalContext(
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


def knowledge_for_prompt(pipeline, results) -> str:
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
    """
    block = pipeline.to_prompt_block(results)
    grounded = any(
        chunk.source.startswith(("graphrag:", "knowledge:"))
        for result in results
        for chunk in result.chunks
    )
    if grounded:
        return block
    return f"{NO_KNOWLEDGE}\n\n{block}" if block else NO_KNOWLEDGE


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

        # RED FLAGS ARE CHECKED BEFORE ANY ANSWERING PATH, not after.
        #
        # Everything below this line can answer and return: the fast path at the
        # next statement, the conversational intents, and the knowledge answer.
        # None of them reached `safety.scan`, which only ran further down once a
        # consultation had already begun. So a question phrased as a QUESTION
        # rather than a complaint - "blood in stool me kya khana chahiye",
        # "seene me dard ke liye kya khaye" - matched the alias index, took the
        # fast path, and was answered with a food chart. The words that should
        # have escalated were the very words that made it look answerable.
        #
        # Scanning the message alone here, not the transcript: at this point the
        # user has typed one line outside any consultation, and the whole-
        # transcript scan further down still runs for everything after that.
        if safety.scan(message):
            return _escalate(context, "red-flag keyword")

        # Fast path: the alias index already named a topic and the wording is a
        # question, not "mujhe X hai". That is exactly what the classifier would
        # answer, so asking it costs ~2.5s of the user's wait for a verdict we
        # already have. Deliberately narrow - anything ambiguous still goes to
        # the model.
        if match_topics(message) and not is_personal_complaint(message):
            route = Route(intent="knowledge")
        else:
            route = await route_message(
                message,
                history=ctx_state.render_history(context),
                greeted=context.greeted,
                # Resolved just above, so an explicit "answer in Hindi from now
                # on" takes effect on THIS reply rather than the next one.
                language=context.language,
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

        if route.intent == "knowledge":
            question_context = ConsultContext(problem=message)
            pipeline, results = await _retrieve(question_context, principal, conversation_id)
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

    if typed and not answers and context.phase in CONSULTING and is_small_talk(typed):
        # "hii" while the cards are open. Settled in code, BEFORE the router, so
        # it cannot depend on a classification that might come back wrong - or
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
        elif aside.intent in CONVERSATIONAL:
            # "hii", "thanks", "haan"  -  answer it and leave the cards standing.
            # Filing these as symptoms is what let a greeting push the intake on.
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
    if safety.is_serious_condition(context.problem):
        context.phase = "completed"
        print(f"[consult] serious condition disclosed: {context.problem[:60]!r}")
        reply = await write_supportive_care(context.problem, context.language)
        context = ctx_state.remember_chat(context, "", reply)
        return ConsultResult(
            kind="chat",
            condition=context.condition,
            message=reply,
            answer=reply,
            context=context,
        )

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

    # --- 1. gather, in prose ----------------------------------------------
    # Replaces the question cards AND the "what would you like in your plan?"
    # step. Both were forms; this is a conversation. The user is never asked to
    # pick from a list, and never has to, to reach a plan.
    if context.phase != "completed":
        gathered = await gather(
            problem=context.problem,
            history=ctx_state.render_history(context),
            symptoms=context.symptoms,
            # The conversation's sticky language, resolved above from what the
            # user actually typed. `context.problem` is the router's Latin
            # restatement, so this must not be re-detected from it.
            language=context.language,
            rounds=context.round,
        )

        context.condition = gathered.condition or context.condition
        context.symptoms = ctx_state._merge_symptoms(context.symptoms, gathered.symptoms)

        # The second of the three replacements for the planner's red flags: the
        # model reading the conversation and saying so outright.
        if gathered.red_flag:
            return _escalate(context, "gathering flagged a red flag")

        if not gathered.ready:
            context.phase = "gathering"
            context.round += 1
            context = ctx_state.remember_chat(context, "", gathered.reply)
            return ConsultResult(
                kind="chat",
                condition=context.condition,
                message=gathered.reply,
                answer=gathered.reply,
                context=context,
            )
        # ready -> fall through and write the plan on this same turn.

    # --- 2. the plan -------------------------------------------------------
    # Everyone gets the complete plan now. The section picker was the second card
    # surface and is gone; `resolve_sections(None)` returns DEFAULT_SECTIONS, so
    # ALWAYS_INCLUDED — "When To See A Doctor" — still cannot be dropped.
    # `context.answers` is only ever populated on a pre-change conversation.
    chosen = context.answers.get(SECTIONS_QUESTION_ID)
    sections = resolve_sections(chosen.options if chosen else None)

    pipeline, results = await _retrieve(context, principal, conversation_id)

    # A serious condition can arrive in an uploaded report rather than in what
    # the user typed - somebody attaches an oncology summary and asks about
    # tiredness. The typed-disclosure check above would never see it, so scan the
    # retrieved report text as well and route to the same supportive reply. A
    # wellness plan on top of a cancer report is the exact failure to avoid.
    report_text = " ".join(
        chunk.text
        for result in results
        for chunk in result.chunks
        if chunk.source.startswith("report:")
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
    details = "\n".join(
        part
        for part in (
            f"Problem: {context.problem}",
            f"Noted: {', '.join(context.symptoms)}" if context.symptoms else "",
            # Only ever non-empty for a consultation that began before the cards
            # were removed and is being finished now.
            ctx_state.intake_summary(context),
            f"--- CONVERSATION ---\n{ctx_state.render_history(context)}",
        )
        if part
    ).strip()
    answer = await write_plan(
        knowledge=knowledge_for_prompt(pipeline, results),
        profile=profile,
        details=details,
        sections=sections,
        language=context.language,
    )

    context.phase = "completed"
    # Remember the plan too, so "explain this in English" works on it just as it
    # does on a general answer.
    context = ctx_state.remember_chat(context, "", answer)
    return ConsultResult(
        kind="answer",
        condition=context.condition,
        answer=answer,
        context=context,
        sources=pipeline.to_sources(results),
    )
