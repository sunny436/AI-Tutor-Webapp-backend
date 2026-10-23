"""The voice tutor's face on a turn, read from what the app already decided about the message: the study scope
(app/intents/scope.py) and the intent router's reading (app/intents, messages.metadata.intent). No model is asked.

The face only shows a manner; it never changes the reply. Only the expression word reaches the browser: never the
intent, its group, a confidence or the scope's reasons. Anything uncertain, refused or unknown is `neutral`.
"""

from __future__ import annotations

from app.intents.scope import ALLOW_SUPPORT, CLARIFY, REDIRECT
from app.intents.taxonomy import ABSTAIN

EXPRESSIONS = ("neutral", "happy", "explaining", "focused", "thinking", "encouraging")

# The router's groups (app/intents/taxonomy.py GROUPS), for an intent it applied.
GROUP_EXPRESSIONS = {
    "understand": "explaining",
    "materials": "explaining",
    "visual_lab": "explaining",
    "solve": "focused",
    "tests": "focused",
    "feedback": "focused",
    "planning": "focused",
    "language": "neutral",
}


def expression_for(intent: dict | None, scope: str | None, min_group_confidence: float) -> str:
    """`intent`: the turn's intent record (None: not read); `scope`: the study scope's decision (None: not read);
    `min_group_confidence`: the router's own INTENT_MIN_GROUP_CONFIDENCE, for a greeting it read (it applies no
    intent to one, so `applied` cannot say how sure it was)."""
    if scope == ALLOW_SUPPORT:  # worried or stuck about studying
        return "encouraging"
    if scope == CLARIFY:  # too vague to tell what they want
        return "thinking"
    if scope == REDIRECT or not intent:
        return "neutral"
    if intent.get("applied"):
        return GROUP_EXPRESSIONS.get(intent.get("group") or "", "neutral")
    confidence = intent.get("groupConfidence")
    if (
        intent.get("group") == ABSTAIN
        and intent.get("reason") == "other"
        and isinstance(confidence, (int, float))
        and confidence >= min_group_confidence
    ):
        return "happy"  # a greeting, thanks or chit-chat
    return "neutral"
