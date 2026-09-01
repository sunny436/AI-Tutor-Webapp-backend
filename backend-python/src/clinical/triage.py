"""
clinical/triage.py
------------------
How urgent is this, and may the normal recommendation flow continue?

WHAT THIS ADDS TO `src/safety.py`, WHICH ALREADY WORKS
`safety.py` answers one question well — is there an emergency keyword — and the
consultation acts on it as a boolean: escalate, or carry on. That is two rungs
where the clinical reality has four. "Blood in vomit" and "acidity for three
weeks that has not improved" are both "not nothing", and today only the first
changes anything; the second gets a wellness plan with no mention that it has
gone on long enough to be looked at.

So this grades rather than switches:

    RED     emergency; nothing else runs, and the reply is the escalation
    ORANGE  see someone promptly; guidance is limited to what is safe meanwhile
    YELLOW  worth a clinician's opinion; the consultation continues, cautiously
    GREEN   ordinary wellness ground

DETERMINISTIC FIRST, AND DETERMINISTIC WINS. `safety.scan` and
`safety.is_serious_condition` are keyword matchers that behave identically on
the day the model is rate-limited, wrong or unreachable, and they set the floor
here. A model verdict may RAISE the level and may never lower it — the failure
this prevents is a confidently reassuring model talking the system down off a
red flag it had already found. `assess()` takes the model's opinion as an
argument rather than calling one, so this module stays pure and testable.

COMBINATIONS, NOT ONLY KEYWORDS. The spec asks for symptom combinations and
context. `_COMBINATIONS` below is where a pair that is unremarkable apart and
serious together lives — vomiting plus no fluids for a day, chest discomfort
plus breathlessness — and `_CONTEXT_ESCALATORS` is where who the patient is
changes the answer: pregnancy, infancy, old age, immunosuppression,
anticoagulants.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src import safety

# The ladder, weakest to strongest. Ordering is the whole API — `max()` over
# this list is how "deterministic wins" is implemented.
LEVELS = ("GREEN", "YELLOW", "ORANGE", "RED")


def rank(level: str) -> int:
    try:
        return LEVELS.index(level)
    except ValueError:
        return 0


def strongest(*levels: str) -> str:
    return LEVELS[max((rank(x) for x in levels), default=0)]


@dataclass(frozen=True)
class Triage:
    """A graded, auditable verdict. Every field exists to be logged."""

    risk_level: str = "GREEN"
    triggering_features: list[str] = field(default_factory=list)
    reason: str = ""
    missing_safety_information: list[str] = field(default_factory=list)
    recommended_action: str = ""
    can_continue_normal_chat: bool = True
    needs_immediate_escalation: bool = False

    def as_dict(self) -> dict:
        return {
            "risk_level": self.risk_level,
            "triggering_features": list(self.triggering_features),
            "reason": self.reason,
            "missing_safety_information": list(self.missing_safety_information),
            "recommended_action": self.recommended_action,
            "can_continue_normal_chat": self.can_continue_normal_chat,
            "needs_immediate_escalation": self.needs_immediate_escalation,
        }


def _rx(*words: str) -> re.Pattern:
    return re.compile("|".join(words), re.IGNORECASE)


# --- ORANGE: see someone soon, but this is not an ambulance -----------------
# Deliberately narrow. Every entry here changes a wellness answer into "get
# this looked at", so a false positive is not free — it is an assistant that
# sounds alarmed about ordinary indigestion.
_ORANGE_PATTERNS = {
    "a symptom lasting longer than a few weeks without improving": _rx(
        r"\b(?:months?|mahin[oe]|hafton|weeks?)\b[^.?!]{0,30}\b(?:se|since|for)\b",
        r"\b(?:1|2|3|4|5|6)\s*(?:month|mahine|mahina)\b",
        r"\bnot\s+(?:improv|better|going)\w*\b",
        r"\btheek\s+nahi\s+ho\s+raha\b",
    ),
    "unintended weight loss": _rx(
        r"\bweight\s+loss\b", r"\blosing\s+weight\b",
        # WINDOWED, not adjacent. "wazan bina koshish ke kam ho raha hai" puts
        # three words between the noun and the verb, and an adjacent-only match
        # read it as GREEN — the benchmark caught it.
        r"\b(?:wazan|vajan|weight)\b[^.?!]{0,30}\b(?:kam|ghat\w*|gir\w*)\b",
        r"वज़न[^।.?!]{0,20}कम",
    ),
    "a lump or swelling": _rx(r"\blump\b", r"\bganth\b", r"\bगांठ\b", r"\bswelling\b"),
    "persistent fever": _rx(
        r"\bfever\b[^.?!]{0,30}\b(?:week|days?|hafte)\b", r"\bbukhar\b[^.?!]{0,30}\bhafte\b",
    ),
    "difficulty swallowing": _rx(
        r"\bdifficulty\s+swallow\w*\b", r"\btrouble\s+swallow\w*\b",
        r"\bnigalne\s+me\w*\s+(?:dikkat|takleef|pareshani)\b",
    ),
    "a report the patient has not discussed with a clinician": _rx(
        r"\breport\b[^.?!]{0,40}\b(?:abnormal|high|low|bad)\b",
    ),
}

# --- YELLOW: worth a clinician's opinion, keep talking ----------------------
_YELLOW_PATTERNS = {
    "a diagnosed long-term condition is involved": _rx(
        r"\bdiabet\w*\b", r"\bsugar\b", r"\bthyroid\b", r"\bbp\b",
        r"\bblood\s+pressure\b", r"\bhypertens\w*\b", r"\basthma\b",
        r"\bकिडनी\b", r"\bkidney\b", r"\bliver\b", r"\bheart\b",
    ),
    "prescription medication is involved": _rx(
        r"\b(?:tablet|capsule|medicine|dawa|dawai|medication)\b",
    ),
    # NOT "cannot sleep" on its own. Insomnia is a complaint people bring here
    # directly, and grading every one of them YELLOW makes the ladder
    # meaningless — the benchmark measured "raat ko neend nahi aati", an
    # ordinary sleep question, coming back YELLOW. What raises concern is a
    # symptom that is COSTING them sleep or work, not sleep being the topic.
    "the symptom is costing them sleep or work": _rx(
        r"\b(?:dard|pain|khujli|itching|jalan)\b[^.?!]{0,40}"
        r"\b(?:so\s+nahi|neend\s+nahi|can'?t\s+sleep|keeps?\s+me\s+awake)\b",
        r"\bkaam\s+nahi\s+kar\s+pa\w*\b", r"\bcan'?t\s+work\b",
    ),
}

# --- combinations: unremarkable apart, serious together ---------------------
_COMBINATIONS = [
    (
        "vomiting with an inability to keep fluids down",
        _rx(r"\bvomit\w*\b", r"\bulti\b", r"\bउल्टी\b"),
        # "cannot", not only "can't" — the apostrophe form is the one people
        # type least often, and this pair is the difference between GREEN and
        # an ambulance.
        _rx(r"\b(?:can'?t|cannot|can\s+not|unable\s+to|not\s+able\s+to)\s+"
            r"(?:keep|hold|retain|drink)\b",
            r"\bnothing\s+stays?\s+down\b",
            # `pa{1,2}ni`, because both spellings are common and `paani?`
            # matches "paan"/"paani" but never "pani".
            r"\bpa{1,2}ni\s+bhi\s+nahi\b", r"\bkuch\s+bhi\s+nahi\s+ruk\w*\b",
            r"\bkuch\s+bhi\s+andar\s+nahi\b"),
        "RED",
    ),
    (
        "chest discomfort with breathlessness",
        _rx(r"\bchest\b", r"\bseene?\b", r"\bसीने\b"),
        _rx(r"\bbreath\w*\b", r"\bsaans\b", r"\bसाँस\b", r"\bshortness\b"),
        "RED",
    ),
    (
        "abdominal pain with persistent vomiting",
        _rx(r"\b(?:stomach|abdomen|pet)\b[^.?!]{0,20}\b(?:pain|dard)\b", r"\bpet\s+dard\b"),
        _rx(r"\bvomit\w*\b", r"\bulti\b"),
        "ORANGE",
    ),
    (
        # An age, combined with a symptom that is ordinary in an adult. Three
        # months old with a high fever is an emergency department, and the
        # benchmark graded it ORANGE until this pair existed.
        "fever in a young infant",
        _rx(r"\b(?:baby|infant|newborn|navjat)\b",
            r"\b(?:[0-9]|1[0-2])\s*(?:month|mahine|mahina|din)\s*(?:ka|ki|old)\b",
            r"\bmahine\s+k[ai]\s+bacch?[ai]\b"),
        _rx(r"\bfever\b", r"\bbukhar\b", r"\btemperature\b", r"\bबुखार\b"),
        "RED",
    ),
    (
        "fever with a severe headache and a stiff neck",
        _rx(r"\bfever\b", r"\bbukhar\b"),
        _rx(r"\bstiff\s+neck\b", r"\bgardan\s+akad\w*\b"),
        "RED",
    ),
]

# --- who the patient is can raise the level --------------------------------
_CONTEXT_ESCALATORS = [
    ("pregnancy", _rx(r"\bpregnan\w*\b", r"\bgarbhvati\b", r"\bगर्भवती\b"), "ORANGE"),
    ("breastfeeding", _rx(r"\bbreastfeed\w*\b", r"\bstanpan\b"), "YELLOW"),
    ("an infant or young child", _rx(r"\b(?:baby|infant|newborn|toddler)\b",
                                     r"\b(?:[0-9]|1[0-2])\s*(?:month|mahine)\s*(?:old|ka)\b"), "ORANGE"),
    ("blood thinners", _rx(r"\bwarfarin\b", r"\bblood\s+thinner\w*\b",
                           r"\banticoagul\w*\b", r"\bclopidogrel\b", r"\baspirin\b"), "YELLOW"),
    # NAMED DRUGS AS WELL AS THE CATEGORY WORD. A patient writes "tacrolimus",
    # never "I am immunosuppressed", and the benchmark graded exactly that
    # patient GREEN.
    ("chemotherapy or immunosuppression",
     _rx(r"\bchemo\w*\b", r"\bimmunosuppress\w*\b", r"\btransplant\b",
         r"\bsteroid\w*\b", r"\btacrolimus\b", r"\bcyclosporin\w*\b",
         r"\bazathioprine\b", r"\bmethotrexate\b", r"\bmycophenolate\b",
         r"\bprednisolone\b", r"\brituximab\b"), "ORANGE"),
    ("recent surgery", _rx(r"\brecent\w*\s+surg\w*\b", r"\boperation\s+hui\b",
                           r"\bsurgery\s+hui\b"), "YELLOW"),
]


def _hits(patterns: dict, text: str) -> list[str]:
    return [label for label, rx in patterns.items() if rx.search(text)]


def assess(
    fragments: list[str],
    *,
    profile_conditions: list[str] | None = None,
    profile_medications: list[str] | None = None,
    model_level: str = "",
    model_reason: str = "",
    serious_condition: str = "",
) -> Triage:
    """Grade this conversation. Pure — no model call, no I/O.

    `fragments` is what the patient has said (`state.user_fragments`), never
    the assistant's own words: the assistant names red-flag symptoms routinely
    when explaining when to see a doctor, and scanning its own output would
    have it triage itself. Same rule `safety.is_serious_condition` already
    follows.

    `model_level` may RAISE the verdict and can never lower it. A model that
    has decided everything is fine must not be able to overrule a keyword
    match that has already fired.
    """
    text = " ".join(f for f in fragments if f)
    features: list[str] = []
    level = "GREEN"

    # 1. The existing emergency scan is the floor and outranks everything.
    if safety.scan(*fragments):
        return Triage(
            risk_level="RED",
            triggering_features=["an emergency red-flag symptom"],
            reason="safety.scan matched an emergency keyword",
            recommended_action="Seek medical care now.",
            can_continue_normal_chat=False,
            needs_immediate_escalation=True,
        )

    # 2. Combinations — each half is ordinary, together they are not.
    for label, first, second, combo_level in _COMBINATIONS:
        if first.search(text) and second.search(text):
            features.append(label)
            level = strongest(level, combo_level)

    # A chronic condition and a prescription are FACTS ABOUT THE PERSON, not
    # things they happen to have typed this turn, so the context checks read
    # the profile as well. The symptom checks below deliberately do not: a
    # symptom is something happening now, and scanning a stored profile for
    # "weight loss" would re-fire a months-old finding on every future turn.
    context_text = " ".join(
        [text, " ".join(profile_conditions or []), " ".join(profile_medications or [])]
    )

    # 3. Single features.
    for label in _hits(_ORANGE_PATTERNS, text):
        features.append(label)
        level = strongest(level, "ORANGE")
    for label in _hits(_YELLOW_PATTERNS, context_text):
        features.append(label)
        level = strongest(level, "YELLOW")

    # 4. Who the patient is.
    for label, rx, ctx_level in _CONTEXT_ESCALATORS:
        if rx.search(context_text):
            features.append(label)
            level = strongest(level, ctx_level)

    # 5. A diagnosed serious condition is never GREEN. It is not an emergency —
    #    somebody living with cancer for a year does not need "go to hospital
    #    now", which is the distinction `safety.py` draws — but it is never
    #    ordinary wellness ground either.
    if serious_condition or safety.is_serious_condition(text):
        features.append("a serious diagnosed condition")
        level = strongest(level, "ORANGE")

    # 6. The model may raise, never lower.
    if model_level:
        raised = strongest(level, model_level.upper())
        if raised != level:
            features.append(f"model judgement: {model_reason or model_level}")
            level = raised

    return Triage(
        risk_level=level,
        triggering_features=features,
        reason="; ".join(features) or "nothing raising concern was found",
        missing_safety_information=_missing_for(level, context_text),
        recommended_action=_ACTIONS[level],
        can_continue_normal_chat=level != "RED",
        needs_immediate_escalation=level == "RED",
    )


_ACTIONS = {
    "GREEN": "Ordinary wellness guidance is appropriate.",
    "YELLOW": "Continue, and mention that a clinician's opinion would be worthwhile.",
    "ORANGE": "Recommend being seen by a clinician promptly; keep guidance to what is safe meanwhile.",
    "RED": "Emergency care now. Nothing else takes priority.",
}


def _missing_for(level: str, text: str) -> list[str]:
    """Safety information whose ABSENCE is itself a reason to ask.

    Only asked for above GREEN: on ordinary ground these are the intrusive
    questions the gathering prompt is explicitly told not to open with.
    """
    if rank(level) < rank("YELLOW"):
        return []
    missing = []
    if not re.search(r"\b(?:age|saal|years?\s+old|umar)\b", text, re.I):
        missing.append("age")
    if not re.search(r"\b(?:medicine|dawa|tablet|medication|koi\s+dawa)\b", text, re.I):
        missing.append("current medicines")
    if rank(level) >= rank("ORANGE") and not re.search(
        r"\b(?:how\s+long|kab\s+se|since|duration)\b", text, re.I
    ):
        missing.append("how long this has been going on")
    return missing
