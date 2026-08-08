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

from src.consult.schema import (
    MAX_CHAT_HISTORY,
    Answer,
    ChatTurn,
    ConsultContext,
    IntakePlan,
    Question,
)

SUPPORTED_VERSION = 2
# The blob rides on every request and is persisted to Convex, so keep it bounded.
MAX_NOTES = 8
MAX_NOTE_CHARS = 400
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
        return ConsultContext.model_validate(raw)
    except Exception as error:  # noqa: BLE001
        print(f"[consult] discarding unreadable context: {error}")
        return ConsultContext()


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
    """
    return {
        "greeted": context.greeted,
        "chat_history": list(context.chat_history),
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

    Uses the problem, the condition and the SELECTED LABELS — deliberately not
    `intake_summary`, which also carries the question text.

    Question wording ("What have you eaten in the last 24 hours?") is noise for a
    similarity search: it drags the embedding towards generic interrogative
    phrasing and away from the topic. Measured on this corpus, an acidity query
    scored 0.408 on the problem alone but only 0.172 once the full summary was
    appended — enough dilution to start dropping notes that genuinely match.
    The answers are the signal; the questions are not.
    """
    parts = [context.problem, context.condition, *selected_labels(context)]
    return " ".join(p for p in parts if p).strip()
