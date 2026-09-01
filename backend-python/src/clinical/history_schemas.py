"""
clinical/history_schemas.py
---------------------------
What a careful clinician would want to know about THIS kind of complaint.

REASONING GUIDES, NOT QUESTIONNAIRES — and the difference is structural, not a
matter of tone. A questionnaire is a list of questions in a fixed order that
gets worked through; what is here is a list of DOMAINS with a reason attached
to each, ranked by what the answer would change. The consultation picks the one
or two that still matter and phrases them itself. Nothing here is ever shown to
the user, and nothing here is ever asked verbatim.

WHY IT IS NEEDED AT ALL. Without it every complaint gets the same generic
questions — how long, what makes it worse — because that is all a general
prompt can know to ask. A stomach problem needs meal timing; a headache needs
triggers and sleep; a skin problem needs what touches it; a cough needs whether
it is dry and how the nights are. `GATHERING_PROMPT` rule 4 already says
exactly this in prose; this is the same knowledge in a form the question
ranker can sort.

RED FLAGS PER FAMILY are the load-bearing half. They are what
`Episode.red_flags_checked` records, so the second consultation about the same
problem does not re-ask what the first one already cleared — and so a gap in
what was checked is visible rather than assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Domain:
    """One thing worth knowing, and why."""

    key: str
    asks: str
    why: str
    # What kind of value the answer has. Read by `decision.VALUE`, so a domain
    # that changes safety outranks one that only personalises.
    kind: str = "diagnostic"


@dataclass(frozen=True)
class Family:
    key: str
    label: str
    matches: re.Pattern
    domains: list[Domain] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    # Ayurveda axes that are genuinely informative for this family. Keeps the
    # Ayurveda reasoner from reaching for agni on a skin rash simply because
    # agni is always available.
    ayurveda_axes: list[str] = field(default_factory=list)


def _rx(*words: str) -> re.Pattern:
    return re.compile("|".join(words), re.IGNORECASE)


def _d(key, asks, why, kind="diagnostic"):
    return Domain(key=key, asks=asks, why=why, kind=kind)


# ORDER IS PRECEDENCE, and it is not alphabetical.
#
# `match()` takes the first hit, so the families that IDENTIFY THEMSELVES by an
# organ or a situation come before the ones that are recognised by a bare
# symptom word. Two real mis-routes made this explicit:
#
#   "peshab me jalan"                 -> gastrointestinal, because "jalan"
#                                        (burning) matched first. It is urinary.
#   "dawa shuru karne ke baad chakkar" -> headache_neurological, because
#                                        "chakkar" matched first. It is a
#                                        suspected drug effect, which changes
#                                        who the question belongs to.
#
# A symptom word like "jalan", "dard" or "chakkar" appears in half the
# families; "peshab", "chemo" and "dawa shuru karne ke baad" appear in exactly
# one. The specific ones therefore go first.
FAMILIES: list[Family] = [
    Family(
        "cancer_supportive", "living with cancer treatment",
        _rx(r"cancer", r"tumour", r"tumor", r"chemo", r"radiation",
            r"radiotherapy", r"oncolog", r"leukemia", r"lymphoma", r"carcinoma",
            r"arbuda"),
        [
            _d("type_and_site", "what type it is and where",
               "nothing sensible can be said without it"),
            _d("current_treatment", "what treatment is running now",
               "decides what must not be suggested at all", "contraindication"),
            _d("oncology_team", "whether they are under a specialist",
               "everything should route through that team", "safety"),
            _d("main_difficulty", "what is troubling them most right now",
               "supportive care is aimed at symptoms, not the disease"),
            _d("side_effects", "nausea, appetite, mouth soreness, fatigue",
               "these are what may safely be helped", "treatment"),
        ],
        ["fever during chemotherapy", "uncontrolled vomiting",
         "breathlessness", "new severe pain", "unusual bleeding or bruising"],
        ["ojas", "agni", "bala"],
    ),
    Family(
        "medication_side_effects", "a medicine that may be causing trouble",
        _rx(r"side\s*effect", r"dawa\s*se", r"medicine\s*(?:se|caus)",
            r"since\s*(?:i\s*)?start\w*\s*(?:the\s*)?(?:tablet|medicine)",
            r"dawa\s*shuru\s*karne\s*ke\s*baad"),
        [
            _d("which_medicine", "which medicine and when it started",
               "timing is most of the answer"),
            _d("timing_relation", "whether the symptom began after starting it",
               "the only thing that makes the link plausible"),
            _d("prescriber", "who prescribed it",
               "this belongs with them, not here", "safety"),
            _d("other_medicines", "everything else they take",
               "interactions are commoner than single-drug effects", "interaction"),
        ],
        ["rash with facial swelling", "difficulty breathing after a dose",
         "yellowing of the eyes", "very dark urine"],
        ["ama", "agni"],
    ),
    Family(
        "women_health", "menstrual and reproductive health",
        _rx(r"period", r"menstru", r"pcos", r"pcod", r"menopaus", r"pregnan",
            r"garbh", r"rajahsrava", r"white\s*discharge", r"leucorr",
            r"fertility", r"conceiv", r"artava"),
        [
            _d("cycle", "how regular the cycle is and how long",
               "regularity is the core of the assessment"),
            _d("flow_pain", "how heavy it is and how painful",
               "separates several distinct problems"),
            _d("pregnancy_status", "whether pregnancy is possible right now",
               "changes what may be suggested at all", "contraindication"),
            _d("associated", "acne, hair growth, weight change",
               "points toward PCOS rather than a cycle issue"),
            _d("contraception_hormones", "any hormonal medication",
               "interacts with several herbs", "interaction"),
        ],
        ["bleeding in pregnancy", "severe pelvic pain", "soaking through protection hourly",
         "bleeding after menopause"],
        ["vata", "pitta", "artava", "rasa"],
    ),
    Family(
        "urinary", "urinary and kidney",
        _rx(r"urin", r"peshab", r"mutra", r"burning\s*while", r"kidney",
            r"gurda", r"stone", r"pathri", r"uti", r"bladder"),
        [
            _d("burning_frequency", "burning, urgency or going more often",
               "the basic infection picture"),
            _d("blood", "any blood in the urine", "changes urgency immediately", "safety"),
            _d("flank_pain", "pain in the back or side", "points at the kidney"),
            _d("fluid_intake", "how much they drink", "the first thing to change", "treatment"),
            _d("kidney_function", "any known kidney problem or test result",
               "makes several herbs and practices unsafe", "contraindication"),
        ],
        ["blood in urine", "fever with back pain", "passing no urine",
         "severe one-sided back pain"],
        ["vata", "pitta", "mutravaha srotas"],
    ),
    Family(
        "thyroid", "thyroid",
        _rx(r"thyroid", r"hypothyroid", r"hyperthyroid", r"tsh", r"goit",
            r"thyronorm", r"levothyrox", r"eltroxin"),
        [
            _d("direction", "whether it is under- or over-active",
               "the advice is opposite in the two"),
            _d("medication_timing", "what they take and when",
               "several herbs and foods interfere with absorption", "interaction"),
            _d("recent_tests", "the most recent TSH if they know it",
               "tells whether this is controlled"),
            _d("symptoms", "weight, energy, hair, cold or heat intolerance",
               "how well controlled it actually feels"),
        ],
        ["palpitations with tremor", "a rapidly enlarging neck swelling",
         "severe drowsiness or confusion"],
        ["kapha", "agni", "vata"],
    ),
    Family(
        "metabolic_diabetes", "blood sugar and metabolism",
        _rx(r"diabet", r"sugar", r"madhumeha", r"insulin", r"hba1c",
            r"prediabet", r"obes", r"weight\s*gain", r"motapa", r"cholesterol"),
        [
            _d("control", "recent sugar readings or HbA1c if they know them",
               "changes how cautious every other suggestion has to be", "safety"),
            _d("medication", "what they take and whether it has changed",
               "several herbs add to glucose-lowering drugs", "interaction"),
            _d("hypo_episodes", "whether they get low-sugar episodes",
               "makes fasting and some herbs unsafe", "safety"),
            _d("diet_pattern", "what a typical day of eating looks like",
               "where the advice will actually land", "treatment"),
            _d("activity", "how much they move",
               "the highest-yield change available", "treatment"),
        ],
        ["very high or very low readings", "confusion or drowsiness",
         "a foot wound that is not healing", "rapid unexplained weight loss"],
        ["kapha", "meda", "agni"],
    ),
    Family(
        "cardiovascular", "blood pressure and the heart",
        _rx(r"blood\s*pressure", r"\bbp\b", r"hypertens", r"heart", r"hriday",
            r"palpitat", r"dhadkan", r"cholesterol", r"stroke"),
        [
            _d("readings", "recent blood-pressure readings if they have them",
               "the difference between reassurance and urgency", "safety"),
            _d("medication", "what they take and whether they take it regularly",
               "several herbs interact with BP medication", "interaction"),
            _d("salt", "how salty the food usually is",
               "the most direct dietary lever", "treatment"),
            _d("symptoms", "headaches, palpitations or breathlessness",
               "symptomatic hypertension is a different situation"),
        ],
        ["chest pain", "breathlessness at rest", "fainting",
         "one-sided weakness or slurred speech", "very high readings"],
        ["pitta", "vata", "rakta"],
    ),
    Family(
        "gastrointestinal", "digestion and the gut",
        _rx(r"acid", r"amlapitta", r"reflux", r"heartburn", r"jalan", r"gas\b",
            r"bloat", r"constipat", r"kabz", r"diarrh", r"loose motion",
            r"stomach", r"pet\b", r"indigest", r"ibs", r"piles", r"bawasir",
            r"ulcer", r"nausea", r"vomit", r"ulti", r"appetite", r"bhookh"),
        [
            _d("timing", "when it happens relative to meals",
               "before meals points one way, after meals another"),
            _d("diet_pattern", "meal timing and how regular meals are",
               "irregular eating is the commonest reversible cause", "treatment"),
            _d("bowel", "what bowel movements are like",
               "separates upper-gut from lower-gut problems"),
            _d("trigger_foods", "which foods make it worse",
               "gives something actionable immediately", "treatment"),
            _d("night_symptoms", "whether it wakes them at night",
               "night symptoms raise the concern level"),
            _d("nsaid_use", "whether they take painkillers regularly",
               "NSAIDs are a common and easily missed cause", "interaction"),
        ],
        ["blood in vomit", "black or tarry stool", "difficulty swallowing",
         "unintended weight loss", "persistent vomiting"],
        ["agni", "ama", "pitta", "vata"],
    ),
    Family(
        "respiratory", "breathing and the chest",
        _rx(r"cough", r"khansi", r"khaansi", r"breath", r"saans", r"asthma",
            r"wheez", r"cold\b", r"sardi", r"sinus", r"throat", r"gala",
            r"chest\s*congest", r"kapha.*cough"),
        [
            _d("dry_or_productive", "whether the cough is dry or brings something up",
               "the most basic split in any cough"),
            _d("duration", "how long it has lasted",
               "over three weeks changes what this needs"),
            _d("night_or_exertion", "whether it is worse at night or on exertion",
               "points toward asthma or reflux"),
            _d("smoking", "whether they smoke or are around smoke",
               "changes both cause and advice", "treatment"),
            _d("fever", "whether there is fever",
               "separates infection from irritation"),
        ],
        ["breathlessness at rest", "coughing blood", "chest pain with breathing",
         "blue lips", "cough lasting more than three weeks"],
        ["kapha", "vata", "ama"],
    ),
    Family(
        "skin", "skin and hair",
        _rx(r"skin", r"twacha", r"rash", r"acne", r"pimple", r"muhas",
            r"eczema", r"psorias", r"itch", r"khujli", r"kushta", r"dandruff",
            # HAIR FALL IS SAID EVERY WHICH WAY: "baal bahut jhad rahe hain",
            # "baal gir rahe hain", "hair fall ho raha hai". Anchoring on the
            # two words being adjacent missed the commonest phrasings.
            r"baal\b.{0,24}\b(jhad|gir|tut|patl)", r"hair.{0,12}(fall|loss|thin)",
            r"ganjapan", r"alopecia", r"hives", r"pigment"),
        [
            _d("distribution", "where on the body it is",
               "distribution is most of the diagnosis in skin"),
            _d("itch", "whether it itches, burns or neither",
               "separates the main families of skin problem"),
            _d("contact", "what touches the area — products, soaps, metals",
               "contact causes are the ones they can act on", "treatment"),
            _d("course", "whether it comes and goes or is constant",
               "episodic and constant behave differently"),
            _d("new_products", "anything new applied or taken recently",
               "includes medicines, which cause rashes", "interaction"),
        ],
        ["rapidly spreading rash with fever", "blistering or peeling skin",
         "swelling of the face, lips or tongue", "a mole that is changing"],
        ["pitta", "kapha", "rakta", "ama"],
    ),
    Family(
        "musculoskeletal", "joints, muscles and back",
        _rx(r"joint", r"knee", r"ghutn", r"back\s*pain", r"kamar", r"neck",
            r"gardan", r"shoulder", r"kandha", r"arthrit", r"sandhi",
            r"muscle", r"sprain", r"stiff", r"akdan"),
        [
            _d("location", "exactly where it hurts and whether it spreads",
               "radiation changes what this is likely to be"),
            _d("morning_stiffness", "whether it is stiff in the morning and for how long",
               "prolonged morning stiffness points at inflammation"),
            _d("swelling", "whether the joint is swollen or warm",
               "separates inflammatory from mechanical"),
            _d("activity_relation", "whether movement helps or worsens it",
               "the single most discriminating question here"),
            _d("injury", "whether there was an injury or a new activity",
               "a mechanical cause needs no further search"),
        ],
        ["numbness or weakness in a limb", "loss of bladder or bowel control",
         "fever with a hot swollen joint", "pain after a significant fall"],
        ["vata", "ama", "srotas"],
    ),
    Family(
        "headache_neurological", "headache and the nervous system",
        _rx(r"headache", r"sar\s*dard", r"sir\s*dard", r"migrain", r"ardhavabhedaka",
            r"dizz", r"chakkar", r"vertigo", r"numb", r"tingl", r"jhunjhun",
            r"seizure", r"faint", r"behosh"),
        [
            _d("pattern", "whether it is one-sided, throbbing or a band",
               "the character separates migraine from tension headache"),
            _d("triggers", "what brings it on",
               "usually the most useful thing they can change", "treatment"),
            _d("aura_visual", "whether vision changes before or during it",
               "aura changes both the diagnosis and the advice"),
            _d("sleep", "how they are sleeping",
               "sleep is both a trigger and a consequence", "treatment"),
            _d("analgesic_frequency", "how often they take painkillers",
               "medication-overuse headache is missed constantly", "interaction"),
        ],
        ["sudden worst-ever headache", "headache with fever and a stiff neck",
         "weakness or numbness on one side", "confusion or difficulty speaking",
         "headache after a head injury"],
        ["vata", "pitta", "nidra"],
    ),
    Family(
        "sleep", "sleep",
        _rx(r"sleep", r"insomnia", r"neend", r"nidra", r"snor", r"kharrat",
            r"anidra", r"wake\s*up"),
        [
            _d("onset_or_maintenance", "whether falling asleep or staying asleep is the problem",
               "the two have different causes and different advice"),
            _d("screen_and_routine", "what the hour before bed looks like",
               "the most changeable factor there is", "treatment"),
            _d("caffeine", "tea and coffee, and how late",
               "commonly the whole explanation", "treatment"),
            _d("daytime_impact", "how the days feel",
               "separates a preference from a disorder"),
            _d("snoring_apnoea", "whether they snore or wake gasping",
               "sleep apnoea needs a clinician, not a routine", "safety"),
        ],
        ["waking gasping or choking", "falling asleep while driving",
         "sleeplessness with low mood or hopelessness"],
        ["vata", "pitta", "nidra"],
    ),
    Family(
        "chronic_pain", "long-standing pain",
        _rx(r"chronic\s*pain", r"fibromyal", r"purana\s*dard", r"years?\s*se\s*dard",
            r"long\s*standing\s*pain"),
        [
            _d("duration_course", "how long, and whether it is changing",
               "distinguishes stable from progressive"),
            _d("what_helps", "what has helped before, even partly",
               "the best predictor of what will help next", "treatment"),
            _d("sleep_mood", "how it affects sleep and mood",
               "both maintain chronic pain and both are treatable", "treatment"),
            _d("analgesic_use", "what painkillers they take and how often",
               "long-term NSAID use carries its own risks", "interaction"),
            _d("function", "what it stops them doing",
               "the outcome that actually matters to them"),
        ],
        ["new neurological symptoms", "unexplained weight loss",
         "night pain that wakes them", "fever with pain"],
        ["vata", "ama", "ojas"],
    ),
    Family(
        "fatigue", "tiredness and low energy",
        _rx(r"fatigue", r"tired", r"thakan", r"kamzor", r"weak", r"low\s*energy",
            r"exhaust", r"lethargy", r"alasya", r"daurbalya"),
        [
            _d("sleep", "how much and how well they sleep",
               "the commonest cause and the most fixable", "treatment"),
            _d("duration", "how long it has been going on",
               "months of it needs looking into"),
            _d("diet_iron", "what they eat, and whether they have had blood tests",
               "anaemia and deficiency are common and treatable"),
            _d("mood", "how their mood has been",
               "low mood and fatigue are hard to separate and both matter"),
            _d("weight_change", "any weight change",
               "changes this from tiredness to something to investigate", "safety"),
        ],
        ["fatigue with breathlessness or chest pain", "unexplained weight loss",
         "fainting", "fatigue with fever lasting weeks"],
        ["ojas", "agni", "bala", "rasa"],
    ),
]


_BY_KEY = {f.key: f for f in FAMILIES}


def match(text: str) -> Family | None:
    """The family this complaint belongs to, or None.

    First match wins and the order above is deliberate: `cancer_supportive`
    sits before `fatigue` so "thakan during chemo" is read as cancer supportive
    care, which is the one that changes what may be offered.
    """
    body = text or ""
    return next((f for f in FAMILIES if f.matches.search(body)), None)


def get(key: str) -> Family | None:
    return _BY_KEY.get(key)


def domains_for(text: str) -> list[Domain]:
    family = match(text)
    return list(family.domains) if family else []


def red_flags_for(text: str) -> list[str]:
    family = match(text)
    return list(family.red_flags) if family else []


def unchecked_red_flags(text: str, already_checked: list[str]) -> list[str]:
    """Red flags for this family that this episode has not covered yet.

    What makes a SECOND consultation about the same problem shorter than the
    first: what was cleared stays cleared.
    """
    done = {c.lower() for c in (already_checked or [])}
    return [f for f in red_flags_for(text) if f.lower() not in done]


def render_guide(text: str, answered: list[str] | None = None) -> str:
    """A short prompt block: what is worth exploring for this complaint.

    Under 400 characters by design. This joins a prompt that is already long,
    and its job is to steer the next question, not to be a curriculum.
    """
    family = match(text)
    if family is None:
        return ""
    done = {a.lower() for a in (answered or [])}
    open_domains = [d for d in family.domains if d.key not in done][:4]
    if not open_domains:
        return ""
    lines = "; ".join(f"{d.asks} ({d.why})" for d in open_domains)
    return (
        f"FOR A COMPLAINT OF THIS KIND ({family.label}), what usually matters "
        f"most: {lines}. Ask about whichever of these would change your advice "
        "MOST — not all of them, and never as a list."
    )
