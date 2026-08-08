"""
consult/repair.py
-----------------
Turns whatever the model actually returned into something the UI can render.

Llama 3.3 via Groq is good at JSON but not perfect: it will occasionally emit a
trailing comma, wrap the object in prose, reuse an option id, invent a `type`, or
return fifteen questions. Every one of those would produce a broken or empty
screen.

The strategy is REPAIR, NEVER REJECT. A slightly wrong plan that renders beats a
correct rejection that leaves the user staring at nothing. Only if repair yields
zero usable questions do we retry the model once, and only once — each attempt
costs 1-3 seconds.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.consult.schema import (
    MAX_CONDITION,
    MAX_LABEL,
    MAX_OPTION_LABEL,
    MAX_OPTIONS,
    MAX_QUESTIONS,
    IntakePlan,
    Option,
    Question,
)

_VALID_TYPES = {"single", "multi", "text"}
_VALID_DISPLAYS = {"chips", "scale", "cards"}


def extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a model reply.

    Handles ```json fences and leading/trailing prose. Returns None on failure —
    unlike the legacy `_extract_json`, it never invents a successful result,
    because the caller's correct fallback differs by round.
    """
    if not text:
        return None

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        for attempt in (candidate, _strip_trailing_commas(candidate)):
            try:
                parsed = json.loads(attempt)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return None


def _strip_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def slugify(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")
    return slug[:40] or fallback


def _unique(slug: str, taken: set[str]) -> str:
    if slug not in taken:
        taken.add(slug)
        return slug
    for suffix in range(2, 100):
        candidate = f"{slug}_{suffix}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    taken.add(slug)
    return slug


def _repair_options(raw: Any, question_slug: str) -> list[Option]:
    if not isinstance(raw, list):
        return []
    options: list[Option] = []
    ids: set[str] = set()
    seen_labels: set[str] = set()

    for index, item in enumerate(raw):
        if isinstance(item, str):
            item = {"label": item}
        if not isinstance(item, dict):
            continue

        label = str(item.get("label") or item.get("text") or "").strip()
        if not label:
            continue
        label = label[:MAX_OPTION_LABEL]

        # Two chips saying the same thing is a model slip, not a real choice.
        normalized = label.lower()
        if normalized in seen_labels:
            continue
        seen_labels.add(normalized)

        options.append(
            Option(
                id=_unique(slugify(item.get("id") or label, f"{question_slug}_{index}"), ids),
                label=label,
                emoji=(str(item["emoji"])[:4] if item.get("emoji") else None),
                red_flag=bool(item.get("red_flag") or item.get("redFlag")),
            )
        )
        if len(options) >= MAX_OPTIONS:
            break
    return options


def _repair_question(raw: Any, index: int, taken_ids: set[str]) -> Question | None:
    if not isinstance(raw, dict):
        return None

    label = str(raw.get("label") or raw.get("question") or raw.get("title") or "").strip()
    if not label:
        return None
    label = label[:MAX_LABEL]

    slug = _unique(slugify(raw.get("id") or label, f"q{index}"), taken_ids)
    options = _repair_options(raw.get("options"), slug)

    q_type = str(raw.get("type") or "single").strip().lower()
    if q_type not in _VALID_TYPES:
        q_type = "multi" if len(options) > 4 else "single"

    display = str(raw.get("display") or "chips").strip().lower()
    if display not in _VALID_DISPLAYS:
        display = "chips"

    # A choice question with nothing to choose between is useless as chips;
    # degrade it to a text field rather than rendering an empty card.
    if q_type in {"single", "multi"} and len(options) < 2:
        q_type, options, display = "text", [], "chips"

    max_select = raw.get("max_select") or raw.get("maxSelect")
    try:
        max_select = int(max_select) if max_select is not None else None
    except (TypeError, ValueError):
        max_select = None

    hint = raw.get("hint") or raw.get("help")
    return Question(
        id=slug,
        label=label,
        hint=(str(hint)[:120] if hint else None),
        type=q_type,  # type: ignore[arg-type]
        display=display,  # type: ignore[arg-type]
        options=options,
        max_select=max_select,
        required=bool(raw.get("required")),
    )


def repair_plan(raw: dict[str, Any] | None) -> IntakePlan:
    """Coerce a parsed model reply into a renderable plan.

    Always returns a plan; `questions` may be empty, which the caller treats as
    "planning failed" and handles per-round.
    """
    if not isinstance(raw, dict):
        return IntakePlan()

    # Accept the few shapes the model drifts towards.
    raw_questions = raw.get("questions")
    if not isinstance(raw_questions, list):
        for key in ("intake", "fields", "form", "items"):
            if isinstance(raw.get(key), list):
                raw_questions = raw[key]
                break
    if not isinstance(raw_questions, list):
        raw_questions = []

    taken_ids: set[str] = set()
    questions: list[Question] = []
    text_questions = 0

    for index, item in enumerate(raw_questions):
        question = _repair_question(item, index, taken_ids)
        if question is None:
            continue
        # At most one free-text field per plan, otherwise the planner regresses
        # towards typed answers and undoes the whole feature.
        if question.type == "text":
            if text_questions >= 1:
                continue
            text_questions += 1
        questions.append(question)
        if len(questions) >= MAX_QUESTIONS:
            break

    condition = str(raw.get("condition") or raw.get("disease") or "").strip()
    note = str(raw.get("note") or raw.get("summary") or "").strip()

    return IntakePlan(
        condition=condition[:MAX_CONDITION],
        note=note[:200],
        questions=questions,
        needs_second_round=bool(
            raw.get("needs_second_round") or raw.get("needsSecondRound")
        ),
    )


def parse_plan(text: str) -> IntakePlan:
    """extract -> repair, in one step."""
    plan = repair_plan(extract_json(text))
    if not plan.questions:
        # Keep the raw reply visible; these logs are how the prompt gets tuned.
        print(f"[consult] planner produced no usable questions. Raw reply:\n{text[:600]}")
    return plan
