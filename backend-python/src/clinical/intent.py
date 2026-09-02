"""
PHASE-1 — the universal intent and subject router.

persona.txt, `intent_router`:

    "Classify the interaction goal before choosing the depth and structure of
     questioning."

WHY THIS EXISTS, in one measured example. Asked "My eGFR is 50.", the system
replied "are you currently managing any diagnosed health conditions... to help
me provide the most relevant Ayurvedic and lifestyle guidance" — it never asked
the age, the test date, the creatinine or the trend, and it opened an Ayurveda
consultation for a modern-medicine interpretation question. That is
`problem_statement.current_failure_pattern` almost word for word, and it
happens because nothing upstream decides WHAT KIND of interaction this is
before the questioning style is chosen.

The existing `router.route_message` classifies ten intents, but they answer a
different question — "is this small talk, a document question, or health?" —
and route to a reply style. These twenty-one answer "what does the user want
out of this exchange?", and they decide how much may be asked and about what.
Both survive: this runs first and hands its verdict down.

DETERMINISTIC FIRST, then the model. Every pattern here was chosen because it
is unambiguous in the language people actually type; the ambiguous middle is
left to the classifier. `spec.confidence_behavior` requires that a confident
classification is never announced to the user, so nothing here is ever spoken.

Feature-flagged (`config.PHASE1_INTENT_ROUTER`) and OFF by default, per
`existing_product_context.instructions` and acceptance criterion 19.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The twenty-one goals, exactly as persona.txt names them. The names are the
# contract: `internal_turn_plan.current_goal` is an "intent_enum" and PHASE-3
# reads these strings, so they are not renamed for tidiness.
GOALS: tuple[str, ...] = (
    "new_symptom",
    "existing_diagnosis",
    "abnormal_lab_result",
    "report_explanation",
    "medicine_information",
    "personalized_medicine_safety",
    "herb_or_supplement_information",
    "personalized_herb_safety",
    "treatment_options",
    "urgency_or_triage",
    "preventive_health",
    "lifestyle_guidance",
    "mental_health",
    "pregnancy_or_reproductive_health",
    "child_health",
    "injury_poisoning_or_exposure",
    "follow_up",
    "second_opinion_preparation",
    "ayurveda_assessment",
    "general_education",
    "multiple_concerns",
)

SUBJECTS: tuple[str, ...] = ("self", "child", "adult_other", "unknown")

# `implementation_phases` PHASE-1: "Quick, standard and detailed interaction
# modes". The mode caps how much may be asked before an outcome is owed;
# PHASE-3's sufficiency engine reads it.
MODES: tuple[str, ...] = ("quick", "standard", "detailed")


@dataclass
class TurnGoal:
    """What the user wants from THIS exchange, and who it is about."""

    goal: str = "new_symptom"
    confidence: float = 0.0
    subject: str = "unknown"
    mode: str = "standard"
    # Why this goal was chosen. Auditable per `reasoning_privacy`: rule ids and
    # short reasons are kept, never free-form model reasoning.
    reason_codes: list[str] = field(default_factory=list)
    # `confidence_behavior`: "If different intents require materially different
    # questioning, ask the user which outcome matters most."
    needs_goal_clarification: bool = False
    candidates: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "goal": self.goal,
            "confidence": round(self.confidence, 2),
            "subject": self.subject,
            "mode": self.mode,
            "reason_codes": list(self.reason_codes),
            "needs_goal_clarification": self.needs_goal_clarification,
            "candidates": list(self.candidates),
        }


# ---------------------------------------------------------------------------
# Subject — "Determine whether the user is asking about themselves or someone
# else" (STAGE-00). It changes the safety rules, not only the pronouns: an
# infant fever is an emergency at an age an adult fever is not.
# ---------------------------------------------------------------------------
_CHILD = re.compile(
    r"\b(my|mere|meri|mera)\s+(son|daughter|baby|child|kid|beta|beti|bacche|baccha|bacchi)\b"
    r"|\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"[\s-]*(year|yr|saal|month|mahine|week|hafte)[\s-]*old\b"
    r"|\b(newborn|toddler|infant|navjat)\b"
    r"|\b(mere|meri)\s+\d{1,2}\s*(saal|mahine)\s+k[ae]\b"
    r"|(मेरे|मेरी)\s*(बेटे|बेटी|बच्चे|बच्ची)",
    re.IGNORECASE,
)
_ADULT_OTHER = re.compile(
    r"\b(my|mere|meri|mera)\s+(mother|father|wife|husband|mom|dad|maa|papa|pita|patni|pati"
    r"|brother|sister|bhai|behen|friend|dost|uncle|aunty|saas|sasur|nani|dadi|nana|dada)\b"
    r"|(मेरी|मेरे)\s*(माँ|माता|पिता|पत्नी|बहन|भाई)",
    re.IGNORECASE,
)
_SELF = re.compile(
    r"\b(i|i'm|i've|my|me|mujhe|mujha|mera|meri|mere|main|maine)\b"
    r"|(मुझे|मेरा|मेरी|मैं)",
    re.IGNORECASE,
)


def detect_subject(text: str) -> str:
    body = text or ""
    # Checked before `self`: "my son has fever" contains "my", and the child is
    # the patient. Whoever is being described wins over whoever is typing.
    if _CHILD.search(body):
        return "child"
    if _ADULT_OTHER.search(body):
        return "adult_other"
    if _SELF.search(body):
        return "self"
    return "unknown"


# ---------------------------------------------------------------------------
# Deterministic goal signals.
#
# Only patterns that are unambiguous in real messages live here. Everything
# else is left to the model rather than guessed at, because a wrong goal
# chooses the wrong questioning style, which is the failure being fixed.
# ---------------------------------------------------------------------------

# A named test carrying a number. This is the eGFR case, and it is deliberately
# recognised on the VALUE rather than on the word "report": "My eGFR is 50" has
# no report, no complaint and no request in it, and every other classifier read
# it as somebody describing a problem.
_LAB_NAME = (
    r"egfr|gfr|creatinine|creat|urea|bun|uric\s*acid|"
    r"hba1c|a1c|fasting\s*(blood\s*)?sugar|fbs|ppbs|random\s*sugar|glucose|"
    # A bare "sugar" only when it is being REPORTED as a value: "my sugar is
    # 300", "sugar level 180". Without that guard "I eat 2 spoons of sugar"
    # would be read as a laboratory result.
    r"blood\s*sugar|sugar\s+(is|level|levels|hai|tha|aaya)|"
    r"tsh|t3|t4|thyroid|"
    r"haemoglobin|hemoglobin|hb|hgb|platelet|wbc|rbc|tlc|esr|crp|"
    r"cholesterol|ldl|hdl|triglyceride|"
    r"sgpt|sgot|alt|ast|bilirubin|alkaline\s*phosphatase|"
    r"vitamin\s*[bd]\s*-?\s*\d*|ferritin|psa|inr"
)
_LAB_VALUE = re.compile(
    rf"\b({_LAB_NAME})\b[^.?!\n]{{0,24}}?\d",
    re.IGNORECASE,
)
_LAB_VALUE_REVERSED = re.compile(
    rf"\d[^.?!\n]{{0,16}}?\b({_LAB_NAME})\b",
    re.IGNORECASE,
)

_REPORT_ASK = re.compile(
    r"\b(explain|samjha|batao|bata|padh|read|check)\b[^.?!\n]{0,30}\b(report|reports)\b"
    r"|\b(report|reports)\b[^.?!\n]{0,30}\b(explain|samjha|batao|me kya|mein kya|kya likha)\b"
    r"|\bmeri\s+report\b|\bmy\s+report\b|(रिपोर्ट)",
    re.IGNORECASE,
)

_TRIAGE_ASK = re.compile(
    r"\bshould\s+i\s+(go|visit|see)\b[^.?!\n]{0,20}\b(hospital|doctor|emergency|er)\b"
    r"|\bis\s+(this|it)\s+(serious|dangerous|an?\s+emergency)\b"
    r"|\b(hospital|doctor)\s+jana\s+chahiye\b"
    r"|\bkya\s+ye\s+(serious|khatarnak|gambhir)\b",
    re.IGNORECASE,
)

_PREVENTIVE = re.compile(
    r"\b(which|what|kaunse|kaun\s*se)\b[^.?!\n]{0,30}\b(tests?|screening|check\s*up|checkup)\b"
    r"|\bscreening\b|\bpreventive\b|\bhealth\s*check\b",
    re.IGNORECASE,
)

_SECOND_OPINION = re.compile(
    r"\bwhat\s+(should|can)\s+i\s+ask\b[^.?!\n]{0,30}\b(doctor|specialist|consultant)\b"
    r"|\bdoctor\s+se\s+kya\s+puch",
    re.IGNORECASE,
)

_INJURY = re.compile(
    r"\b(accidentally|by\s+mistake|galti\s+se)\b[^.?!\n]{0,40}\b(took|khaa|khaya|liya|drank)\b"
    r"|\boverdose\b|\btoo\s+many\s+(tablets|pills)\b|\bpoison|\bzahar\b"
    r"|\b(snake|dog|scorpion)\s*bite\b|\bjal\s*gaya\b|\bburn(t|ed)?\b",
    re.IGNORECASE,
)

_MENTAL = re.compile(
    r"\b(hopeless|depress\w*|anxious|anxiety|panic|suicidal|worthless|"
    r"can'?t\s+cope|no\s+will\s+to\s+live)\b"
    r"|\b(udaas|nirasha|ghabrahat|bechaini|tanav|mann\s+nahi\s+lagta)\b",
    re.IGNORECASE,
)

_PREGNANCY = re.compile(
    r"\b(pregnan\w*|garbh\w*|expecting|conceive|conception|trimester|"
    r"periods?|menstrua\w*|breastfeed\w*|stanpan)\b"
    r"|(गर्भ|प्रेग्नेंट)",
    re.IGNORECASE,
)

_FOLLOW_UP = re.compile(
    r"\b(better|worse|improved|no\s+change|same\s+as\s+before|since\s+(starting|taking))\b"
    r"[^.?!\n]{0,40}\b(after|since|days?|weeks?|din|hafte)\b"
    r"|\b(aaram|fayda)\s+(hai|hua|mila|nahi)\b",
    re.IGNORECASE,
)

_AYURVEDA_ASK = re.compile(
    r"\bayurved\w*\s+(perspective|point\s+of\s+view|nazariye|hisab)\b"
    r"|\b(assess|dekho|batao)\b[^.?!\n]{0,24}\bayurved",
    re.IGNORECASE,
)

_TREATMENT_OPTIONS = re.compile(
    r"\bwhat\s+(treatments?|options?|therapies)\b"
    r"|\btreatment\s+options?\b|\bilaj\s+ke\s+(options|tarike)\b",
    re.IGNORECASE,
)

# A herb/supplement, versus a pharmaceutical. The split matters because
# `herb_or_supplement_information` must separate traditional use from clinical
# evidence (`universal_acceptance_examples`, turmeric), and
# `medicine_information` must not.
_HERB = re.compile(
    r"\b(ashwagandha|ashwgandha|turmeric|haldi|triphala|tulsi|brahmi|shatavari|"
    r"guggulu|guggul|neem|amla|giloy|arjuna|shankhpushpi|jatamansi|punarnava|"
    r"yashtimadhu|licorice|mulethi|saunf|jeera|ajwain|methi|fenugreek|"
    r"chyawanprash|churna|kadha|herb|jadi\s*buti|supplement|"
    r"ayurvedic\s+(powder|medicine|product|formulation)|powder)\b",
    re.IGNORECASE,
)
_DRUG = re.compile(
    r"\b(metformin|ibuprofen|paracetamol|crocin|dolo|omeprazole|pantoprazole|"
    r"amlodipine|atorvastatin|thyronorm|levothyroxine|insulin|aspirin|"
    r"antibiotic|tablet|capsule|syrup|injection|steroid|painkiller)\b",
    re.IGNORECASE,
)

# Multiple concerns. `universal_acceptance_examples` requires three problem
# entries from "fever, back pain and also want to understand my thyroid
# report", so this counts DISTINCT concern markers rather than conjunctions —
# "fever and chills" is one illness described twice, not two problems.
_CONCERN_NOUN = re.compile(
    r"\b(fever|bukhar|pain|dard|report|cough|khansi|cold|sardi|headache|sar\s*dard|"
    r"acidity|gas|constipation|kabz|diarrh\w*|dast|vomit|ulti|nausea|"
    r"rash|itch|khujli|swelling|sujan|weakness|kamzori|thakan|fatigue|"
    r"sleep|neend|anxiety|stress|sugar|bp|thyroid|weight|periods?)\b",
    re.IGNORECASE,
)
_ALSO = re.compile(
    r"\b(also|and\s+also|aur\s+bhi|iske\s+alawa|plus|as\s+well\s+as|saath\s+hi)\b"
    r"|\band\s+(want|would\s+like)\b",
    re.IGNORECASE,
)


# "What is migraine?" - the spec's first acceptance example. It carries no
# information word ("symptoms", "causes", "benefits"), so the existing
# informational detector does not fire on it, and a bare definition request
# was falling through to `new_symptom` and opening an intake.
_DEFINITION = re.compile(
    r"^\s*(what|what'?s)\s+(is|are)\b"
    r"|\btell\s+me\s+about\b"
    r"|\b(kya|kaun\s*sa)\s+(hai|hota\s+hai|hoti\s+hai)\s*\??\s*$"
    r"|\b(define|definition\s+of|meaning\s+of|explain\s+what)\b"
    r"|\bke\s+bare\s+me[in]?\s+bata",
    re.IGNORECASE,
)


def _distinct_concerns(text: str) -> list[str]:
    """Different concern words, de-duplicated, in the order they appear."""
    seen: list[str] = []
    for match in _CONCERN_NOUN.finditer(text or ""):
        word = match.group(0).lower()
        if word not in seen:
            seen.append(word)
    return seen


def detect_mode(text: str) -> str:
    """quick | standard | detailed — how much may be asked before an outcome."""
    body = (text or "").lower()
    if re.search(r"\b(quick|jaldi|short|briefly|bas\s+itna|seedha|just\s+tell)\b", body):
        return "quick"
    if re.search(r"\b(detail|detailed|vistar|poora|complete|thoroughly)\b", body):
        return "detailed"
    return "standard"


def classify(text: str, *, has_attachment: bool = False) -> TurnGoal:
    """The deterministic pass. `confidence` 0 means "ask the model".

    Ordered by decisiveness, not by frequency: an injury or a mental-health
    disclosure outranks whatever else the sentence also contains, because the
    questioning style they require is not negotiable by the rest of the message.
    """
    body = (text or "").strip()
    subject = detect_subject(body)
    mode = detect_mode(body)

    def made(goal: str, confidence: float, *reasons: str) -> TurnGoal:
        return TurnGoal(
            goal=goal,
            confidence=confidence,
            subject=subject,
            mode=mode,
            reason_codes=list(reasons),
        )

    if not body:
        return made("general_education", 0.0, "empty")

    # 1. Things that change the questioning style absolutely.
    if _INJURY.search(body):
        return made("injury_poisoning_or_exposure", 0.95, "injury_pattern")
    if _MENTAL.search(body):
        return made("mental_health", 0.9, "mental_health_pattern")
    if _TRIAGE_ASK.search(body):
        return made("urgency_or_triage", 0.9, "triage_question")

    # 2. Multiple concerns, before any single-topic rule can claim one of them.
    concerns = _distinct_concerns(body)
    if len(concerns) >= 3 or (len(concerns) >= 2 and _ALSO.search(body)):
        goal = made("multiple_concerns", 0.85, "distinct_concerns")
        goal.candidates = concerns
        return goal

    # 3. A laboratory value. Recognised on the number, not on the word
    #    "report" — "My eGFR is 50" contains neither a complaint nor a request.
    if _LAB_VALUE.search(body) or _LAB_VALUE_REVERSED.search(body):
        return made("abnormal_lab_result", 0.9, "lab_name_with_value")

    if _REPORT_ASK.search(body) or (has_attachment and len(body) < 60):
        return made("report_explanation", 0.85, "report_request")

    if _SECOND_OPINION.search(body):
        return made("second_opinion_preparation", 0.85, "second_opinion")
    if _PREVENTIVE.search(body):
        return made("preventive_health", 0.8, "preventive_question")
    if _TREATMENT_OPTIONS.search(body):
        return made("treatment_options", 0.8, "treatment_options")
    if _AYURVEDA_ASK.search(body):
        return made("ayurveda_assessment", 0.85, "ayurveda_requested")
    if _PREGNANCY.search(body):
        return made("pregnancy_or_reproductive_health", 0.8, "pregnancy_context")

    # 4. Substances: information versus permission. `asks_if_safe_for_me` is
    #    the same detector the knowledge path already uses, imported late to
    #    keep this module free of a circular import.
    from src.consult.router import asks_for_information, asks_if_safe_for_me

    personal = asks_if_safe_for_me(body)
    if _HERB.search(body):
        return made(
            "personalized_herb_safety" if personal else "herb_or_supplement_information",
            0.85,
            "herb_named",
        )
    if _DRUG.search(body):
        return made(
            "personalized_medicine_safety" if personal else "medicine_information",
            0.85,
            "drug_named",
        )

    if subject == "child":
        return made("child_health", 0.8, "child_subject")

    if _FOLLOW_UP.search(body):
        return made("follow_up", 0.75, "progress_report")

    # 5. A question about a condition, versus having one.
    if asks_for_information(body) or _DEFINITION.search(body):
        return made("general_education", 0.8, "informational_phrasing")

    # Undecided on purpose. PHASE-1's model pass fills these in; until it does,
    # the caller keeps its existing behaviour rather than acting on a guess.
    return made("new_symptom", 0.0, "no_deterministic_signal")
