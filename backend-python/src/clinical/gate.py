"""
clinical/gate.py
----------------
The last thing between a generated answer and the reader.

WHY THIS EXISTS
Everything upstream — retrieval, reasoning, the plan prompt — PROPOSES. Until
now nothing DISPOSED: `write_plan`'s output went straight to the user, and the
only checks that existed (`responder._warn_if_medicine`,
`_warn_if_leaked_terms`) print to the log and change nothing. A rule that only
warns is a rule the product does not have.

Three jobs, all deterministic, in the order they matter:

  1. WHAT MAY BE OFFERED AT ALL, from the triage level. At RED nothing but the
     escalation goes out; at ORANGE, education and low-risk lifestyle only. A
     retrieved passage cannot buy its way past this, which is what "do not
     allow retrieved GraphRAG content to bypass safety checks" means in code.

  2. WHAT WAS ACTUALLY ASKED FOR. Somebody who says "sirf yoga batao" and gets
     the whole six-section plan has been ignored. This was a measured
     regression: after the intake started seeing the current turn, richer
     retrieval made the model volunteer unrequested sections in roughly a third
     of scoped requests. The prompt asks for the right sections and the model
     mostly complies; `enforce_sections` makes "mostly" into "always".

  3. WHO IS READING IT. Every intervention the answer names is checked against
     this person's active medicines, conditions and allergies
     (`clinical/interactions.py`). Blocked ones are removed with a short honest
     line in their place.

NOTHING HERE REWRITES CLINICAL PROSE. It removes whole sections and whole
sentences, and it says so. `responder._warn_if_medicine`'s docstring is right
that a regex quietly rephrasing a health answer is worse than the problem —
so this deletes and discloses rather than editing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.clinical import interactions
from src.clinical.triage import rank
from src.consult.sections import SECTION_LIBRARY

# What kind of thing an answer may contain, weakest to strongest commitment.
CATEGORIES = (
    "EDUCATION",
    "LOW_RISK_LIFESTYLE",
    "DIETARY_GUIDANCE",
    "YOGA_OR_EXERCISE_INFORMATION",
    "TRADITIONAL_AYURVEDA_INFORMATION",
    "AYURVEDA_INTERVENTION",
    "MEDICAL_EVALUATION",
    "URGENT_CARE",
)

# Triage level -> what may be offered. Cumulative downward: GREEN allows
# everything below it too.
_ALLOWED_BY_LEVEL = {
    "GREEN": set(CATEGORIES),
    "YELLOW": set(CATEGORIES) - {"AYURVEDA_INTERVENTION"} | {"MEDICAL_EVALUATION"},
    "ORANGE": {"EDUCATION", "LOW_RISK_LIFESTYLE", "MEDICAL_EVALUATION", "URGENT_CARE"},
    "RED": {"URGENT_CARE"},
}


@dataclass
class GateResult:
    """What went out, what did not, and why. Every field is for the audit log."""

    answer: str = ""
    approved: bool = True
    allowed_categories: list[str] = field(default_factory=list)
    dropped_sections: list[str] = field(default_factory=list)
    blocked_interventions: list[dict] = field(default_factory=list)
    cautioned_interventions: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "approved": self.approved,
            "allowed_categories": sorted(self.allowed_categories),
            "dropped_sections": list(self.dropped_sections),
            "blocked_interventions": list(self.blocked_interventions),
            "cautioned_interventions": list(self.cautioned_interventions),
            "notes": list(self.notes),
        }


def allowed_categories(risk_level: str) -> set[str]:
    return set(_ALLOWED_BY_LEVEL.get(risk_level, _ALLOWED_BY_LEVEL["GREEN"]))


_HEADING_LINE = re.compile(r"^\s*\*\*(?P<heading>[^*]+)\*\*\s*$")


def split_sections(answer: str) -> list[tuple[str, str]]:
    """[(heading or "", body)] — the preamble first, with an empty heading.

    Matched on WHOLE LINES with the `**Bold**` form, exactly as
    `sections.looks_like_plan` and the frontend's `answer-sections.tsx` do. A
    heading quoted inside a sentence is not a section, and treating it as one
    would cut an answer in half mid-paragraph.
    """
    blocks: list[tuple[str, str]] = []
    heading, body = "", []
    for line in (answer or "").splitlines():
        found = _HEADING_LINE.match(line)
        if found:
            blocks.append((heading, "\n".join(body).strip()))
            heading, body = found.group("heading").strip(), []
        else:
            body.append(line)
    blocks.append((heading, "\n".join(body).strip()))
    return [b for b in blocks if b[0] or b[1]]


def enforce_sections(answer: str, wanted_keys: list[str]) -> tuple[str, list[str]]:
    """Keep only the sections that were asked for. Returns (answer, dropped).

    `wanted_keys` are SECTION_LIBRARY keys, as `resolve_sections` returns them.
    The preamble (before the first heading) is always kept: it is the sentence
    that shows the reader they were listened to.

    Does nothing when the text is not in the sectioned format — a conversational
    reply has no sections to enforce.
    """
    # SECTION_LIBRARY stores the heading WITH its asterisks ("**Food Chart**")
    # because that is what the prompt must emit verbatim; `split_sections`
    # returns it without them. Normalising both sides is not cosmetic — with
    # one side unstripped nothing ever matched and every section was dropped,
    # which is the most destructive possible failure of this function.
    wanted = {
        SECTION_LIBRARY[k][0].strip().strip("*").strip()
        for k in wanted_keys
        if k in SECTION_LIBRARY
    }
    if not wanted:
        return answer, []
    blocks = split_sections(answer)
    if not any(h for h, _b in blocks):
        return answer, []

    kept, dropped = [], []
    for heading, body in blocks:
        if not heading:
            if body:
                kept.append(body)
            continue
        if heading in wanted:
            kept.append(f"**{heading}**\n{body}".rstrip())
        else:
            dropped.append(heading)
    return "\n\n".join(part for part in kept if part).strip(), dropped


_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?", re.UNICODE)


def _remove_sentences_naming(text: str, names: list[str]) -> tuple[str, int]:
    """Drop whole sentences that name a blocked intervention.

    Whole sentences, never a word: cutting "ashwagandha" out of "take
    ashwagandha at night" leaves an instruction to take something unnamed,
    which is worse than either keeping it or removing it.
    """
    if not names:
        return text, 0
    matchers = [interactions._RULES[n][0] for n in names if n in interactions._RULES]
    if not matchers:
        return text, 0
    removed = 0
    out_lines = []
    for line in (text or "").splitlines():
        pieces = _SENTENCE.findall(line)
        if not pieces:
            out_lines.append(line)
            continue
        keep = []
        for piece in pieces:
            if any(m.search(piece) for m in matchers):
                removed += 1
                continue
            keep.append(piece)
        rebuilt = "".join(keep).strip()
        # A line that was ONLY the blocked advice disappears; a line that had
        # other content keeps it.
        if rebuilt or not line.strip():
            out_lines.append(rebuilt if rebuilt else line if not line.strip() else "")
    return "\n".join(l for l in out_lines if l is not None), removed


def screen(
    answer: str,
    *,
    risk_level: str = "GREEN",
    wanted_sections: list[str] | None = None,
    medications: list[str] | None = None,
    conditions: list[str] | None = None,
    allergies: list[str] | None = None,
    language: str = "hinglish",
) -> GateResult:
    """Run an answer past the gate. Pure — no model, no I/O."""
    result = GateResult(answer=answer or "", allowed_categories=sorted(allowed_categories(risk_level)))

    # 1. At RED nothing but the escalation goes out. The caller should not have
    #    reached here at all; this is the backstop that makes that true rather
    #    than assumed.
    if risk_level == "RED":
        result.approved = False
        result.notes.append("RED triage: no wellness guidance may be shown")
        return result

    # 2. Only what was asked for.
    if wanted_sections:
        result.answer, result.dropped_sections = enforce_sections(
            result.answer, wanted_sections
        )
        if result.dropped_sections:
            result.notes.append(
                "removed sections the reader did not ask for: "
                + ", ".join(result.dropped_sections)
            )

    # 3. Only what is safe for THIS person.
    verdicts = interactions.screen_text(
        result.answer, medications=medications, conditions=conditions, allergies=allergies
    )
    blocked = [v for v in verdicts if v.status == "blocked"]
    cautioned = [v for v in verdicts if v.status == "caution"]
    result.blocked_interventions = [v.as_dict() for v in blocked]
    result.cautioned_interventions = [v.as_dict() for v in cautioned]

    if blocked:
        result.answer, removed = _remove_sentences_naming(
            result.answer, [v.intervention for v in blocked]
        )
        result.notes.append(
            f"removed {removed} sentence(s) naming: "
            + ", ".join(v.intervention for v in blocked)
        )
        result.answer = (result.answer.rstrip() + "\n\n" + _WITHHELD[
            language if language in _WITHHELD else "hinglish"
        ]).strip()

    # Interventions at ORANGE are not on the table at all, blocked or not.
    if rank(risk_level) >= rank("ORANGE") and "AYURVEDA_INTERVENTION" not in result.allowed_categories:
        named = interactions.find_interventions(result.answer)
        if named:
            result.answer, removed = _remove_sentences_naming(result.answer, named)
            result.notes.append(
                f"{risk_level} triage: removed {removed} sentence(s) offering an "
                "intervention while a clinical review is outstanding"
            )

    result.answer = re.sub(r"\n{3,}", "\n\n", result.answer).strip()
    return result


# Said in place of what was removed. Honest about the fact that something was
# withheld — silently dropping advice teaches the reader nothing and leaves
# them to find it somewhere less careful.
_WITHHELD = {
    "hinglish": (
        "Ek baat aur — aapki current dawaiyon aur health condition ko dekhte hue "
        "kuch cheezein maine yahan jaan-bujhkar nahi likhi hain. Unke liye apne "
        "doctor ya kisi qualified Ayurveda practitioner se poochh lijiyega."
    ),
    "english": (
        "One more thing — given your current medicines and health conditions, "
        "there are a few things I have deliberately left out here. Please ask "
        "your doctor or a qualified Ayurveda practitioner about those."
    ),
    "devanagari": (
        "एक बात और — आपकी मौजूदा दवाओं और सेहत को देखते हुए कुछ चीज़ें मैंने "
        "जान-बूझकर यहाँ नहीं लिखी हैं। उनके बारे में अपने डॉक्टर या किसी योग्य "
        "आयुर्वेद चिकित्सक से पूछ लीजिएगा।"
    ),
}
