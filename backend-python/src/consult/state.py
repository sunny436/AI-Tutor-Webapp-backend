"""
consult/state.py
----------------
Owns the consultation's session state.

The server is stateless: each turn the client echoes back the `context` it was
given. That keeps the backend horizontally scalable and, more importantly, means
the future RAG stages fetch server-owned data by identity instead of trusting
whatever the browser sent.

The security-critical function here is `resolve_answers`. The client submits
option *ids*; labels are resolved server-side against the plans we previously
issued. Labels are never read from the request, so the browser cannot inject
arbitrary text into the answer prompt.
"""

from __future__ import annotations

import datetime as _dt

from src.consult.schema import (
    Fact,
    LEGACY_PHASES,
    MAX_CHAT_HISTORY,
    Answer,
    ChatTurn,
    ConsultContext,
    IntakePlan,
    PatientProfile,
    Question,
)

SUPPORTED_VERSION = 2
# Profile caps. Same reasoning as MAX_SYMPTOMS below — this is persisted per
# user and rides every request — but roomier, because a real person can
# genuinely be on six medicines and these are not a vector query.
MAX_PROFILE_ITEMS = 12
MAX_PROFILE_ITEM_CHARS = 80
# Scalars are short by nature ("34", "female", "software engineer").
MAX_PROFILE_SCALAR_CHARS = 60
# The blob rides on every request and is persisted to Convex, so keep it bounded.
MAX_NOTES = 8
MAX_NOTE_CHARS = 400
# Retrieval keywords: short, and few. These go straight into the vector query, so
# the caps are a quality guard rather than a storage one — see `search_query`.
MAX_SYMPTOMS = 10
MAX_SYMPTOM_CHARS = 40
# Generous: a six-section plan runs ~3k characters and must survive intact for
# "translate this" to be faithful.
MAX_LAST_ANSWER = 6000


def load_context(raw: dict | None) -> ConsultContext:
    """Rebuild context from the client. Unknown/broken shapes start fresh."""
    if not isinstance(raw, dict):
        return ConsultContext()
    if raw.get("v") not in (None, SUPPORTED_VERSION):
        # An older persisted blob — degrade to a new consult rather than crash.
        return ConsultContext()
    try:
        context = ConsultContext.model_validate(raw)
    except Exception as error:  # noqa: BLE001
        print(f"[consult] discarding unreadable context: {error}")
        return ConsultContext()

    # A conversation persisted before the card intake was replaced. Its phase is
    # `collecting` or `choosing`, neither of which exists in the product any
    # more — carry it into `gathering` so the consultation simply continues in
    # prose from whatever was already collected.
    #
    # SUPPORTED_VERSION deliberately stays 2. Bumping it would make the check
    # above discard every one of these blobs, which is the outcome this mapping
    # exists to prevent: the user's half-finished consultation would disappear
    # and the assistant would greet them as if they had just arrived.
    if context.phase in LEGACY_PHASES:
        print(f"[consult] migrating legacy phase {context.phase!r} -> 'gathering'")
        # Anything already tapped is real detail the user gave us. Fold it into
        # the new retrieval signal so the plan is still built from it.
        context.symptoms = _merge_symptoms(context.symptoms, selected_labels(context))
        context.phase = "gathering"

    return context


def _merge_symptoms(existing: list[str], incoming: list[str]) -> list[str]:
    """Append new keywords, de-duplicated case-insensitively and bounded.

    Bounded because this rides on every request and feeds the vector query;
    letting it grow turn after turn would dilute the query in exactly the way
    `search_query` documents.
    """
    seen = {s.lower() for s in existing}
    merged = list(existing)
    for item in incoming:
        cleaned = (item or "").strip()[:MAX_SYMPTOM_CHARS]
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            merged.append(cleaned)
    return merged[-MAX_SYMPTOMS:]


_PROFILE_SCALARS = ("age", "sex", "occupation", "reproductive")
_PROFILE_LISTS = (
    "conditions", "medications", "supplements", "allergies",
    "surgeries", "lifestyle", "family_history",
)
# Human labels for the prompt. The model never sees a field name.
_PROFILE_LABELS = {
    "age": "Age", "sex": "Sex", "occupation": "Work",
    "reproductive": "Reproductive history",
    "conditions": "Diagnosed conditions", "medications": "Current medicines",
    "supplements": "Supplements/herbs", "allergies": "Allergies",
    "surgeries": "Past surgeries/hospitalisations", "lifestyle": "Lifestyle",
    "family_history": "Family history",
}


def _now() -> str:
    """UTC date stamp. Date, not time: this records when a fact was last
    confirmed, and hour-level precision would imply a certainty the source —
    somebody mentioning it in conversation — does not have."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def merge_profile(
    existing: PatientProfile, incoming: dict, removals: dict | None = None
) -> tuple[PatientProfile, bool]:
    """Fold newly stated facts into the profile. Returns (profile, changed).

    SCALARS REPLACE. "Actually I am 30 now" must correct 29, not sit beside
    it — an age that only ever grows a list is worse than useless.

    LISTS MERGE, case-insensitively de-duplicated, reusing the same shape as
    `_merge_symptoms` above. Someone who mentions a second allergy still has
    the first one.

    REMOVAL IS EXPLICIT ONLY. `removals` carries facts the user has directly
    contradicted ("I'm not on metformin any more"). Nothing is ever dropped
    because it merely stopped being mentioned: silence is not retraction, and
    silently losing "penicillin allergy" is the worst bug this function could
    have.

    `changed` is returned so the caller can skip the Convex write on a turn
    that revealed nothing — most turns reveal nothing.

    Pure and side-effect free, so the rules above are unit-testable without a
    model in the loop.
    """
    merged = existing.model_copy(deep=True)
    changed = False

    for key in _PROFILE_SCALARS:
        value = str(incoming.get(key) or "").strip()[:MAX_PROFILE_SCALAR_CHARS]
        if value and value.lower() != (getattr(merged, key) or "").lower():
            setattr(merged, key, value)
            changed = True

    for key in _PROFILE_LISTS:
        raw = incoming.get(key)
        if not isinstance(raw, list):
            continue
        current = list(getattr(merged, key))
        seen = {f.value.lower(): f for f in current}
        for item in raw:
            # Accept a bare string (what the extractor sends today) or a dict
            # carrying provenance. Anything the model marked as its own
            # inference is DROPPED, never stored — PatientProfile's rule is
            # "user-stated facts only", and this is where it is enforced
            # rather than merely documented.
            if isinstance(item, dict):
                value = str(item.get("value") or "").strip()
                incoming_fact = {k: v for k, v in item.items() if k != "value"}
            else:
                value, incoming_fact = str(item or "").strip(), {}
            value = value.strip(".,;")[:MAX_PROFILE_ITEM_CHARS]
            if not value:
                continue
            if incoming_fact.get("source") == "inferred":
                continue
            existing_fact = seen.get(value.lower())
            if existing_fact is None:
                seen[value.lower()] = Fact(
                    value=value,
                    first_seen_at=_now(),
                    last_confirmed_at=_now(),
                    **{k: v for k, v in incoming_fact.items()
                       if k in ("source", "confidence", "status")},
                )
                current.append(seen[value.lower()])
                changed = True
                continue
            # ALREADY KNOWN. Saying it again is a re-confirmation, which is
            # information: it is what stops a year-old "active" being read as
            # though it were still fresh. A changed status is a real change.
            existing_fact.last_confirmed_at = _now()
            new_status = incoming_fact.get("status")
            if new_status and new_status != existing_fact.status:
                existing_fact.status = new_status
                changed = True
        if len(current) > MAX_PROFILE_ITEMS:
            current = current[-MAX_PROFILE_ITEMS:]
            changed = True
        setattr(merged, key, current)

    for key, values in (removals or {}).items():
        if key not in _PROFILE_LISTS or not isinstance(values, list):
            continue
        drop = {str(v or "").strip().lower() for v in values if str(v or "").strip()}
        if not drop:
            continue
        # RETRACTION IS A STATUS CHANGE, NOT A DELETE.
        #
        # "maine metformin band kar diya" means the drug is HISTORICAL, not
        # that it never happened. Deleting the row loses that they were on it,
        # which is exactly the history a later interaction check wants. It is
        # excluded from `active()`, so nothing reasons about it as current,
        # and `render_profile` shows it as stopped.
        touched = False
        for fact in getattr(merged, key):
            if fact.value.lower() in drop and fact.status != "historical":
                fact.status = "historical"
                fact.last_confirmed_at = _now()
                touched = True
        if touched:
            changed = True

    return merged, changed


_STATUS_WORDS = {
    "historical": "in the past, stopped",
    "resolved": "resolved",
    "uncertain": "not confirmed",
    "contradicted": "they have since said otherwise",
    "unknown": "unclear",
}


def render_profile(profile: PatientProfile) -> str:
    """What is already known, as prose for a prompt. Empty string when nothing.

    DELIBERATELY NOT A FIELD QUEUE. The model is shown what it already knows
    and left to work out what is still worth asking, exactly as it already
    does for `missing_info`. Handing it a list of unfilled fields is what
    turns a consultation into a form — it gets worked through in order.

    Field names never appear; the labels are the words a person would use.
    """
    lines = []
    for key in _PROFILE_SCALARS:
        value = getattr(profile, key)
        if value:
            lines.append(f"{_PROFILE_LABELS[key]}: {value}")
    for key in _PROFILE_LISTS:
        facts = getattr(profile, key)
        if not facts:
            continue
        # STATUS IS SHOWN ONLY WHEN IT CHANGES THE MEANING. "metformin" and
        # "metformin (in the past, stopped)" must not read alike to the model —
        # that is the whole point of tracking status — but tagging every active
        # fact "(active)" would be noise in a block the prompt asks it to read
        # as prose about a person.
        rendered = [
            f.value
            if f.status == "active"
            else f"{f.value} ({_STATUS_WORDS.get(f.status, f.status)})"
            for f in facts
        ]
        lines.append(f"{_PROFILE_LABELS[key]}: {', '.join(rendered)}")
    return "\n".join(lines)


def remember_chat(
    context: ConsultContext, user_text: str, reply: str
) -> ConsultContext:
    """Append one exchange to the rolling conversation memory.

    Without this the assistant answered every message as if it were the first,
    which is why "I don't need help, I was just texting" got the welcome message
    all over again.
    """
    turns = list(context.chat_history)
    if user_text.strip():
        turns.append(ChatTurn(role="user", text=user_text.strip()[:400]))
    if reply.strip():
        turns.append(ChatTurn(role="assistant", text=reply.strip()[:400]))
        # Keep anything with real content in full, so "explain that in English"
        # has the whole thing to work from. Short acknowledgements ("Theek hai
        # bhai") aren't worth referring back to and would only displace a real
        # answer the user is more likely to mean.
        if len(reply.strip()) >= 120:
            context.last_answer = reply.strip()[:MAX_LAST_ANSWER]
    context.chat_history = turns[-MAX_CHAT_HISTORY:]
    return context


def remember_user_message(context: ConsultContext, text: str) -> ConsultContext:
    """Record what the user just said BEFORE it is answered, not after.

    `remember_chat` records a finished exchange, so it can only run once a
    reply exists. Every prompt built earlier in the same turn therefore read a
    transcript that stopped at the assistant's previous question — the user's
    current message was simply not in it. `gather()` asked "kis type ka cancer
    hai?", the user answered "blood cancer hai", and the next call to `gather`
    still could not see that answer, so it asked the identical question again.
    Measured in production on 2026-08-31: turns 1 and 2 of the deep-dive came
    back byte-for-byte identical.

    `add_note` did keep the text, but notes are not part of the transcript and
    `render_history` — which is what the prompt actually reads — never showed
    them.

    IDEMPOTENT, AND THAT IS LOAD-BEARING. The new-complaint restart in
    `graph.run_turn` already records the typed message and then falls through
    to `gather` instead of returning, so an unguarded append would show that
    message to the model twice and make it look like the user said it twice.
    Compared against the same `[:400]` truncation `remember_chat` applies, so
    a long message matches itself rather than slipping past the guard.
    """
    cleaned = (text or "").strip()[:400]
    if not cleaned:
        return context
    last = context.chat_history[-1] if context.chat_history else None
    if last is not None and last.role == "user" and last.text == cleaned:
        return context
    turns = [*context.chat_history, ChatTurn(role="user", text=cleaned)]
    context.chat_history = turns[-MAX_CHAT_HISTORY:]
    return context


def render_history(context: ConsultContext) -> str:
    """The conversation so far, as the router prompt reads it."""
    if not context.chat_history:
        return "(this is the first message)"
    return "\n".join(
        f"{'User' if t.role == 'user' else 'You'}: {t.text}" for t in context.chat_history
    )


def carry_conversation(context: ConsultContext) -> dict:
    """The parts of a conversation that survive starting a new consultation.

    A consultation resets the intake, but the chat that led to it still happened —
    forgetting it would make the assistant greet the user again mid-conversation.

    `language` belongs here for the same reason, and its absence was a real bug.
    `run_turn` resolves the language at the top of every turn and stores it on the
    context, but starting a consultation builds a FRESH ConsultContext — so the
    answer was computed and then immediately thrown away, and every consultation
    ran with `language=""`. With no language named, the model chose one: an
    English question came back in Hinglish, and changing the language of a later
    message changed nothing, because nothing was ever being carried in the first
    place.

    `round` belongs here too, and its absence meant NO PLAN WAS EVER WRITTEN.

    Restarting a consultation built a fresh context with `round` back at 0, and
    the restart fires whenever a typed reply classifies as health + personal —
    which an ordinary answer to a gathering question does. Traced live, before
    and after this fix was needed:

        "mujhe gas ho rahi hai"           -> gathering, round 1
        "2 hafte se"                      -> gathering, round 2
        "spicy khane ke baad badhta hai"  -> gathering, round 1   <- reset
        "bas yahi hai"                    -> gathering, round 1
        "plan bana do"                    -> gathering, round 1

    `gathering.MAX_GATHERING_ROUNDS` is the guard for a model that will not stop
    asking, and it is checked against this counter — so a counter that keeps
    resetting disables the guard entirely and the intake runs forever. The user
    is asked question after question and never receives the plan they came for.

    Carrying it is also what the ceiling means: it counts how long we have been
    questioning THIS PERSON, not this topic. Someone who drifts from gas to
    indigestion has still been answering questions for four rounds.
    """
    return {
        "greeted": context.greeted,
        "chat_history": list(context.chat_history),
        "language": context.language,
        "round": context.round,
        # RISK CROSSES THE RESET. A new complaint does not undo a red flag the
        # person has already disclosed — somebody who said they cannot keep
        # fluids down and then starts a consultation about their skin is still
        # somebody who cannot keep fluids down. Without this the fresh
        # ConsultContext would default `risk_level` back to "" and the
        # conversation would quietly return to writing wellness plans.
        "risk_level": context.risk_level,
        "risk_reason": context.risk_reason,
        # The person does not stop having diabetes because they started a
        # consultation about their skin. Carried for the same reason risk is:
        # a fresh ConsultContext would default it away and the assistant would
        # ask everything again, which is precisely the form-filling experience
        # the profile exists to remove.
        "patient_profile": context.patient_profile.model_copy(deep=True),
        "profile_loaded": context.profile_loaded,
        "serious_condition": context.serious_condition,
        # EPISODES CROSS THE RESET, and that is the whole point of them.
        #
        # A new complaint builds a fresh ConsultContext, which is what used to
        # throw the previous problem's reasoning away: someone who moved from
        # acidity to a knee and back had to answer everything about the acidity
        # again. The episode list carries what was learned about each problem,
        # so switching topic costs nothing and coming back costs nothing.
        "episodes": [e.model_copy(deep=True) for e in context.episodes],
        "active_episode_id": context.active_episode_id,
    }


def record_plan(context: ConsultContext, plan: IntakePlan) -> ConsultContext:
    """Remember the questions we just issued so their ids can be resolved later."""
    context.round += 1
    context.condition = plan.condition or context.condition
    context.needs_second_round = plan.needs_second_round
    # Only the current round's questions are needed for resolution, plus the
    # previous round's so a late/duplicate submit still resolves.
    context.asked = (context.asked + plan.questions)[-(2 * 6) :]
    return context


def resolve_answers(
    context: ConsultContext, submitted: dict | None
) -> tuple[ConsultContext, int]:
    """Merge submitted answers into context, resolving ids against issued plans.

    Returns the context and how many answers were recognised. Unknown ids are
    dropped silently (stale plan, back button, or a tampered payload).
    """
    if not isinstance(submitted, dict):
        return context, 0

    by_id: dict[str, Question] = {q.id: q for q in context.asked}
    recognised = 0

    for question_id, value in submitted.items():
        question = by_id.get(str(question_id))
        if question is None:
            continue

        if isinstance(value, dict):
            option_ids = value.get("options") or []
            free_text = value.get("text")
        elif isinstance(value, list):
            option_ids, free_text = value, None
        else:
            option_ids, free_text = [], value

        valid_ids = {o.id for o in question.options}
        chosen = [str(o) for o in option_ids if str(o) in valid_ids]
        if question.type == "single":
            chosen = chosen[:1]
        elif question.max_select:
            chosen = chosen[: question.max_select]

        text = str(free_text).strip()[:MAX_NOTE_CHARS] if free_text else None
        if not chosen and not text:
            continue

        # Keyed by question id, so re-answering a card simply overwrites.
        context.answers[question.id] = Answer(options=chosen, text=text)
        recognised += 1

    return context, recognised


def add_note(context: ConsultContext, note: str | None) -> ConsultContext:
    """Fold free-typed text into the context without disturbing the intake."""
    cleaned = (note or "").strip()
    if cleaned:
        context.notes = (context.notes + [cleaned[:MAX_NOTE_CHARS]])[-MAX_NOTES:]
    return context


def selected_labels(context: ConsultContext) -> list[str]:
    """Every human-readable label the user actually chose, plus typed text.

    This is what safety scanning runs over — the model writes the chip labels, so
    a red-flag phrase can appear in an option that no keyword check of the
    original problem statement would ever see.
    """
    by_id: dict[str, Question] = {q.id: q for q in context.asked}
    labels: list[str] = []

    for question_id, answer in context.answers.items():
        question = by_id.get(question_id)
        if question is None:
            continue
        option_labels = {o.id: o.label for o in question.options}
        labels.extend(option_labels[oid] for oid in answer.options if oid in option_labels)
        if answer.text:
            labels.append(answer.text)

    labels.extend(context.notes)
    return labels


def user_fragments(context: ConsultContext) -> list[str]:
    """Only what the USER said — never the assistant's own words.

    `safety_fragments` below deliberately includes the assistant's turns,
    which is right for the red-flag keyword scan: those keywords are phrases
    a person reports ("ulti me khoon aa raha hai"), and the assistant echoing
    one back is still worth catching.

    `is_serious_condition` is the opposite case and must NOT use that list.
    It matches 42 bare condition NAMES on a word boundary — "cancer", "tb",
    "hiv" — and the assistant says several of them routinely while explaining
    when to see a doctor. Scanning its own output would make the assistant
    diagnose the user with whatever it had just mentioned.
    """
    fragments = [context.problem, context.condition, *context.symptoms, *context.notes]
    fragments.extend(t.text for t in context.chat_history if t.role == "user")
    fragments.extend(selected_labels(context))
    # Conditions the person stated about themselves. A diagnosis given in
    # passing during an earlier consultation is still a diagnosis, and it must
    # reach `is_serious_condition` even after the sentence that carried it has
    # been evicted from `chat_history` (MAX_CHAT_HISTORY = 24).
    # `.active(...)`, not every condition ever recorded: a RESOLVED cancer is
    # not a serious condition disclosure today, and re-firing the deep-dive on
    # it would answer a question the person is no longer asking.
    fragments.extend(context.patient_profile.active("conditions"))
    return [f for f in fragments if f]


def safety_fragments(context: ConsultContext) -> list[str]:
    """Every piece of user-supplied text worth scanning for a red flag.

    THIS IS THE REPLACEMENT FOR THE CARDS' PRIMARY RED-FLAG MECHANISM, and it
    deliberately covers more text than the mechanism it replaces.

    `safety.scan` used to run over the tapped option labels, and its docstring is
    explicit that keyword matching was the BACKSTOP for the planner's own
    `red_flag` markers rather than the only defence. Those markers are gone with
    the cards, so the keyword scan has to widen: it now reads the WHOLE
    conversation, not just the opening complaint.

    That matters because of where a red flag actually appears. "I have acidity"
    is harmless; "there was blood in it this morning", typed three turns later,
    is not — and under the old flow that sentence was only ever seen if the
    planner happened to have written it as an option.

    Note this is one of THREE defences, not the only one. The gathering step sets
    `red_flag` itself, and `safety.is_serious_condition` still runs on the
    problem and on retrieved report text, both unchanged.
    """
    fragments = [context.problem, context.condition, *context.symptoms, *context.notes]
    # The transcript, both sides. The assistant's own turns are included on
    # purpose: it may have repeated back a symptom the user typed in a message
    # long since pushed out of the history window.
    fragments.extend(turn.text for turn in context.chat_history)
    # Anything tapped in a consultation that predates the conversational flow.
    fragments.extend(selected_labels(context))
    return [f for f in fragments if f]


def selected_red_flags(context: ConsultContext) -> list[str]:
    """Labels the planner itself marked as warranting a doctor."""
    by_id: dict[str, Question] = {q.id: q for q in context.asked}
    flagged: list[str] = []
    for question_id, answer in context.answers.items():
        question = by_id.get(question_id)
        if question is None:
            continue
        flags = {o.id: o.label for o in question.options if o.red_flag}
        flagged.extend(flags[oid] for oid in answer.options if oid in flags)
    return flagged


def intake_summary(context: ConsultContext) -> str:
    """Render the collected answers as readable "Question: Answer" lines."""
    by_id: dict[str, Question] = {q.id: q for q in context.asked}
    lines: list[str] = []

    for question_id, answer in context.answers.items():
        question = by_id.get(question_id)
        if question is None:
            continue
        option_labels = {o.id: o.label for o in question.options}
        parts = [option_labels[oid] for oid in answer.options if oid in option_labels]
        if answer.text:
            parts.append(answer.text)
        if parts:
            lines.append(f"{question.label}: {', '.join(parts)}")

    for note in context.notes:
        lines.append(f"User added: {note}")

    return "\n".join(lines)


def search_query(context: ConsultContext) -> str:
    """What the retrieval layer should search for.

    Problem, condition, and SHORT KEYWORDS — never the conversation.

    The measurement that governs this function has not changed, only where the
    keywords come from. On this corpus an acidity query scored 0.408 on the
    problem alone but only 0.172 once the full collected text was appended —
    enough dilution to start dropping notes that genuinely match. Interrogative
    and conversational wording drags the embedding toward generic phrasing and
    away from the topic.

    That is why the conversational flow does NOT put the transcript here. The
    gathering step returns `symptoms` — "gas", "after meals", "spicy food" — and
    those are the signal, exactly as the tapped option labels were before it.
    Feeding `chat_history` in instead would reproduce the 0.172 case precisely.

    `selected_labels` is still included so a consultation persisted mid-cards
    keeps retrieving on what the user had already tapped; it returns nothing for
    conversations started after the change.
    """
    parts = [
        context.problem,
        context.condition,
        *context.symptoms,
        *selected_labels(context),
    ]
    return " ".join(p for p in parts if p).strip()
