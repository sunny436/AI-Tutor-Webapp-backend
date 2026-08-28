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
routing we need. The old `src/graph.py` LangGraph flow has been deleted; this is
now the only orchestration, and `/jobs/run` calls it too.
"""

from __future__ import annotations

import asyncio
import re
from typing import Callable

import config
from src import safety
from src.consult import state as ctx_state
from src.consult.gathering import MAX_GATHERING_ROUNDS, gather
from src.consult.offline import offline_answer
from src.retrieval import graphrag
# `write_plan` is deliberately absent: GraphRAG writes the plan now. Everything
# still here is a job GraphRAG cannot do, because its request carries no history
# and no instructions beyond the query — reworking the answer already on screen
# ("isko english me samjhao"), answering a general question, and the supportive
# reply for a serious disclosure.
from src.consult.responder import (
    NO_KNOWLEDGE,
    rework_answer,
    write_knowledge,
    write_supportive_care,
)
from src.knowledge import match_topics
from src.consult.router import (
    CONVERSATIONAL,
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


# The instruction that turns a free-form reply into the six sections the
# frontend renders as cards. There is no format parameter on the vendor's API -
# `query`, `k`, `graph_hops`, `exclude_relations` is the whole request - so the
# instruction has to travel inside the query itself.
#
# MEASURED at 6/6 headings, with and without a document filter. The wording is
# load-bearing: change it only with a re-measurement, not by eye.
_SECTION_INSTRUCTION = (
    "Jawab bilkul in 6 headings mein do, isi order mein, har heading ko "
    "**Heading** ki tarah likho: **Root Cause**, **Changes To Make**, "
    "**Yoga & Breathing**, **Food Chart**, **Daily Routine**, "
    "**When To See A Doctor**"
)


def _wants_full_plan(context: ConsultContext) -> bool:
    """Is this turn asking for the whole six-section plan, or one part of it?

    A plan already written means the next ask is a follow-up, whatever its
    wording. `phase` becomes "completed" only after the plan is generated, so on
    the turn that first produces one this is still False - which is exactly
    right.

    This exists because the vendor reported the failure from their side: every
    call we made carried the six-heading template regardless of what the user
    typed, so "hn yr b iska liya yoga btao" - just tell me the yoga - came back
    as the entire card set for the second time. Reproduced here before changing
    anything: 6/6 headings, 1101 characters, on a one-line follow-up.

    `is_followup_request` does not catch that phrasing and should not be made
    to: it is a narrow classifier for "tell me more" and "say it in English".
    Whether a plan already exists is a fact we hold, not a guess about wording.
    """
    return not (context.phase == "completed" and bool(context.last_answer))


def _plan_query(context: ConsultContext, asked: str = "") -> str:
    """What we ask GraphRAG for, when GraphRAG writes the plan.

    DELIBERATELY NOT THE TRANSCRIPT. `query` is one string doing two jobs: it is
    the embedding used for retrieval AND the question handed to the model. The
    vendor was explicit that padding it shifts the embedding away from the real
    question, and that short follow-ups suffer worst - which is exactly the case
    that matters in a symptom conversation. So it carries the complaint and what
    gathering understood, and nothing else.

    THE TEMPLATE IS NOT ALWAYS APPENDED. It used to be, on every single call,
    and the vendor found the consequence in their request logs before we found
    it in a bug report: a user asking only for the yoga got the whole card set
    again, because the model was being told to produce six headings no matter
    what the person had typed.

    It also cost retrieval on every call. `query` is one string doing two jobs -
    the embedding for retrieval AND the question for the model - so 213
    characters of pure instruction, carrying no topical signal at all, competed
    with the symptom words for weight in the vector. On a follow-up the
    instruction was most of the string.

    So: a fresh plan gets the complaint and the template. A follow-up gets the
    topic and the user's own words, and no template.

    THE TOPIC HAS TO TRAVEL WITH IT. Sending the follow-up alone was tried and
    is worse than the bug it fixes: "hn yr b iska liya yoga btao" carries no
    topical signal at all - "iska" is "for this", and the service has no memory
    of what "this" was - so it retrieved nothing and answered "I don't have
    enough information to answer that." The vendor said as much in August:
    a bare follow-up "has almost no retrieval signal of its own".

    Prefixing the complaint is the same move `english_handle` makes for Hinglish
    and the same one their own reply recommends: rewrite the follow-up into a
    question that stands on its own before it leaves us.
    """
    complaint = " ".join(
        part for part in (context.problem, ", ".join(context.symptoms)) if part
    ).strip()

    if not _wants_full_plan(context) and asked.strip():
        narrow = f"{complaint} — {asked.strip()}" if complaint else asked.strip()
        return narrow[: graphrag.MAX_QUERY_CHARS]

    room = graphrag.MAX_QUERY_CHARS - len(_SECTION_INSTRUCTION) - 2
    return f"{complaint[:room]}\n\n{_SECTION_INSTRUCTION}"


def _sticky_topic(context: ConsultContext) -> str | None:
    """The note this consultation is about, however the wording has drifted.

    `context.problem` alone is not enough. A typed reply that classifies as
    health + personal restarts the consultation and REWRITES `problem` with that
    reply, so a detail volunteered late replaces the complaint:

        "I have acidity"       -> problem "acidity"              -> acidity.md
        "for 3 weeks"          -> problem "acidity"              -> acidity.md
        "burning after meals"  -> problem "burning after meals"  -> NOTHING

    and the plan for an acidity consultation then went out unscoped, which is
    the blending this whole change exists to stop.

    So: the current problem if it still names a note, otherwise the most recent
    thing the user said that does. Newest-first, so someone who genuinely
    changes subject is followed rather than pinned to their first complaint.
    """
    claimed = match_topics(context.problem or "")
    if claimed:
        return claimed[0]
    for turn in reversed(context.chat_history):
        if turn.role != "user":
            continue
        claimed = match_topics(turn.text or "")
        if claimed:
            return claimed[0]
    return None


async def _plan_from_graphrag(
    context: ConsultContext, asked: str = ""
) -> tuple[str, str | None, bool]:
    """Write the plan. Returns (answer, source filename, served_offline).

    NO `document_ids`. THE VENDOR'S CORPUS DECIDES, NOT OURS. Scoping to one
    note meant naming a filename we hold locally, so anything they added or
    deleted on their side had no effect until somebody edited this repo. The
    founder's call, made twice with the costs on the table, is that their corpus
    should be the live one - upload a note there and it answers from it, delete
    one and it stops, with nothing to deploy here.

    Two measured costs, recorded so nobody rediscovers them as surprises:

      - CITATIONS COME BACK EMPTY. Filtered, 4-5 resolve; unfiltered, zero, in
        every sample. `sources` therefore falls through to what retrieval saw
        rather than what the answer actually used, and the reader is not shown
        which note it came from.
      - IT MIXES NOTES. "gas aur bloating ke baare mein aur batao" cited
        back-pain.md for "naram gadda ... AC seedha kamar par - yeh sab gas ko
        badha sakte hain". A soft mattress is not a cause of gas. `document_ids`
        exists because the vendor shipped it to stop exactly this.

    There is also a dated risk: zero validated citations is one of the two
    triggers for the vendor's abstain check. It is in shadow mode today, so it
    computes and logs without changing the response. When they turn it on, this
    request shape is the one it suppresses. Ask them to say so before they do.

    `sticky` is the topic the CONSULTATION is about, taken from the original
    complaint rather than the latest message. It is now used only to choose the
    note for the offline fallback, and it stays local, so it still works when
    the service is unreachable - which is precisely when it is needed.
    """
    note = _sticky_topic(context)
    query = _plan_query(context, asked)

    try:
        body = await asyncio.to_thread(graphrag.answer, query)
        answer = (body.get("answer") or "").strip()
        if answer:
            cited = [c.get("filename") for c in body.get("citations") or []]
            return answer, next((c for c in cited if c), note), False
        print("[consult] GraphRAG returned an empty answer")
    except Exception as error:
        print(f"[consult] GraphRAG could not write the plan: {error}")

    if note:
        offline = offline_answer(note)
        if offline:
            # LOUD on purpose. A fallback nobody notices is a service that looks
            # healthy while quietly answering from static text.
            print(f"[consult] SERVING THE OFFLINE FALLBACK from {note}")
            return offline, note, True

    return "", note, False


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
    _typed_now = (free_text or "").strip()
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
    # GRAPHRAG WRITES THE PLAN NOW, not our own model.
    #
    # It can be given no rules - the request is `query`, `k`, `graph_hops`,
    # `exclude_relations` and nothing else, and its prompt template is fixed and
    # shared across every tenant - so everything we are accountable for has to
    # sit OUTSIDE it. That is why `safety.scan` runs above this, why the
    # gathering red-flag check runs above this, and why a flagged turn returns
    # long before reaching here. It is also why the section instruction has to
    # travel inside the query: there is no other channel.
    #
    # `sections` is still resolved above and still cannot drop "When To See A
    # Doctor"; the instruction asks for all six every time.
    # `asked` is what the user typed THIS turn. Without it a follow-up cannot be
    # told apart from a fresh complaint, and every turn asks for six headings.
    answer, source_note, served_offline = await _plan_from_graphrag(
        context, asked=typed or message
    )

    if not answer:
        # Neither the service nor the note produced anything. Say so plainly
        # rather than returning an empty plan that renders as a blank screen.
        answer = (
            "Abhi main aapke liye plan nahi bana pa raha hoon. "
            "Thodi der baad dobara koshish karein."
        )
        source_note = None

    context.phase = "completed"
    # Remember the plan too, so "explain this in English" works on it just as it
    # does on a general answer.
    context = ctx_state.remember_chat(context, "", answer)
    sources = pipeline.to_sources(results)
    if source_note:
        label = "Ayurveda notes (offline)" if served_offline else "Reference documents"
        sources = [{"section": label, "source": source_note, "score": None}]
    return ConsultResult(
        kind="answer",
        condition=context.condition,
        answer=answer,
        context=context,
        sources=sources,
    )
