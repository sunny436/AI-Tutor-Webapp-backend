import re

"""
safety.py
---------
A simple safety check that runs on every user message BEFORE we give any
wellness advice.

If the message contains "red-flag" words that could mean a serious or
emergency situation, we stop the normal flow and tell the user to seek
medical help immediately. It is better to be over-cautious here.
"""

# These are simple keyword groups. In a bigger product this would also use the
# LLM to catch phrasing that keywords miss, but keywords are a solid, fast start.
RED_FLAG_KEYWORDS = [
    # heart / breathing
    "chest pain", "can't breathe", "cannot breathe", "shortness of breath",
    "difficulty breathing", "heart attack",
    # stroke / neuro
    "stroke", "face drooping", "slurred speech", "sudden numbness",
    "severe headache", "loss of consciousness", "fainted", "unconscious",
    # bleeding / injury
    "severe bleeding", "bleeding heavily", "coughing blood", "vomiting blood",
    "blood in stool", "accident", "deep wound",
    # severe / other
    "severe pain", "suicidal", "suicide", "self harm", "self-harm",
    "seizure", "high fever", "not breathing", "poison", "overdose",
    # Pregnancy: only escalate on genuine warning signs. A bare "pregnant" used
    # to fire here, which meant every PCOS, fertility or prenatal-yoga question
    # was refused outright — and the intake planner will legitimately generate
    # pregnancy chips for those conditions.
    "pregnancy bleeding", "bleeding while pregnant", "pregnant and bleeding",
    "labour pain", "labor pain", "water broke",
]

# HINGLISH AND DEVANAGARI.
#
# Everything above is English and PHRASE-ORDERED — "vomiting blood". This
# product is Hinglish-first, and its users write "ulti me khoon" or "vomit me
# blood aaya", neither of which contains the substring "vomiting blood". So the
# entire English list above simply did not fire for most of the people using it.
#
# It mattered less while the card intake existed: the planner wrote per-condition
# `red_flag` options ("Blood in stool") and those were the PRIMARY mechanism,
# with this keyword scan as the documented backstop. The cards are gone, so this
# scan is now a primary defence and has to cover the language it is used in.
#
# PHRASES, NEVER BARE WORDS. "khoon" alone would fire on "khoon ki kami"
# (anaemia) — a diet question, not an emergency — and refusing to answer it
# would be its own kind of failure. Likewise "daura" is not listed alone,
# because it is a substring of "dauran" ("during").
RED_FLAG_KEYWORDS += [
    # bleeding
    "khoon aa", "khoon nikal", "khoon bah", "blood aa", "blood nikal",
    "ulti me khoon", "ulti mein khoon", "ulti me blood", "ulti mein blood",
    "vomit me khoon", "vomit mein khoon", "vomit me blood", "vomit mein blood",
    "blood in vomit", "blood vomit", "khoon ki ulti",
    "stool me khoon", "stool mein khoon", "stool me blood", "stool mein blood",
    "latrine me khoon", "potty me khoon", "tatti me khoon",
    "kala stool", "kaala stool", "black stool", "tarry stool",
    # chest / breathing
    "seene me dard", "seene mein dard", "chhati me dard", "chhaati me dard",
    "chest me dard", "chest mein dard",
    "saans nahi aa", "saans nhi aa", "saans phool", "saans lene me dikkat",
    "dam ghut", "damm ghut",
    # collapse / neuro
    "behosh", "behoshi", "mirgi", "daura pad", "chakkar aakar gir",
    # self-harm
    "khudkushi", "khudkhushi", "jaan dene", "marne ka mann", "atmahatya",
    # Devanagari
    "खून आ", "खून निकल", "उल्टी में खून", "मल में खून", "शौच में खून",
    "सीने में दर्द", "छाती में दर्द", "सांस नहीं आ", "साँस नहीं आ",
    "बेहोश", "मिर्गी", "खुदकुशी", "आत्महत्या",
]

# Diagnosed conditions that are treated by a doctor, not managed with a food
# chart. These are NOT emergencies — someone living with cancer for a year does
# not need "go to hospital now" — but building them a lifestyle plan as if it
# were acidity would be both useless and insulting.
#
# Kept separate from RED_FLAG_KEYWORDS for exactly that reason: different
# situation, different answer.
SERIOUS_CONDITIONS = [
    "cancer", "tumour", "tumor", "chemo", "chemotherapy", "radiation",
    "leukemia", "lymphoma", "carcinoma", "kainsar",
    # "tv" and "tibi" are how TB is normally written in Hinglish ("mujhe tv hai").
    # Without them a TB disclosure fell through to the ordinary symptom router and
    # opened a bloating questionnaire.
    "tb", "tuberculosis", "tv disease", "tv hai", "tv ha", "tibi", "t.b",
    "hiv", "aids",
    "kidney failure", "kidney fail", "renal failure", "dialysis",
    "liver failure", "cirrhosis", "hepatitis",
    "heart failure", "bypass", "angioplasty", "pacemaker",
    "epilepsy", "seizures", "paralysis", "stroke ke baad",
    "thalassemia", "sickle cell", "transplant", "autoimmune",
    "lupus", "multiple sclerosis", "parkinson", "alzheimer",
]

# What to say instead. It acknowledges what they said, does not pretend Ayurveda
# treats it, and offers the one thing this assistant honestly can offer.
SERIOUS_CONDITION_MESSAGE = (
    "Aapne jo bataya wo bahut badi baat hai, aur aapka isse guzarna aasan nahi "
    "raha hoga. Shukriya ki aapne share kiya. 🌿\n\n"
    "Main saaf-saaf batana chahta hoon: **iska ilaaj sirf aapke doctor ke paas "
    "hai**, aur Ayurveda uski jagah nahi le sakta. Jo treatment chal raha hai use "
    "kabhi band ya kam mat kijiye.\n\n"
    "Haan, main iske **saath-saath** in cheezon mein madad kar sakta hoon — "
    "taakat aur bhookh banaye rakhna, halka aur asaani se pachne wala khana, "
    "neend behtar karna, aur bahut halki saans ki practice jo thakan aur tanav "
    "mein aaram de. Yeh sab aapke doctor ki salah ke andar rehkar hi.\n\n"
    "**Ek zaroori baat:** koi bhi jadi buti ya supplement shuru karne se pehle "
    "apne doctor ko zaroor batayein — kai cheezein chal rahi dawa ka asar badha "
    "ya ghata deti hain.\n\n"
    "Bataiye, abhi sabse zyada kya pareshan kar raha hai — kamzori, bhookh na "
    "lagna, neend, ya kuch aur? Main usi par dhyan deta hoon."
)


# Word boundaries, not substrings. The old test was
#     f" {word} " in lowered or word in lowered
# whose second clause is a plain substring match, so short entries fired inside
# ordinary words. Measured:
#
#     "mujhe hives ho rahe hain"      -> True   via "hiv"
#     "footbath se pair ka dard"      -> True   via "tb"
#     "outbreak"                      -> True   via "tb"
#
# Hives is squarely this product's domain, and the user was handed the
# cancer/HIV message for it. `\b` still matches the multi-word entries
# ("kidney failure", "stroke ke baad") and the escaped dot in "t.b".
_SERIOUS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in SERIOUS_CONDITIONS) + r")\b",
    re.IGNORECASE,
)


def is_serious_condition(text: str) -> bool:
    """A diagnosed condition this assistant must not build a wellness plan for."""
    return bool(_SERIOUS_RE.search(text or ""))


# The message we show when a red flag is found.
ESCALATION_MESSAGE = (
    "⚠️ **Please seek medical help right away.**\n\n"
    "What you described may be serious. Please contact a doctor immediately or "
    "call your local emergency number / go to the nearest hospital.\n\n"
    "For your safety, I am not giving wellness advice for this. Your health "
    "comes first — please get medical care now."
)


def is_emergency(text: str) -> bool:
    """Return True if the message looks like a serious/emergency situation."""
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in RED_FLAG_KEYWORDS)


def scan(*fragments: str) -> bool:
    """Emergency check across several pieces of text at once.

    The card-based intake made this necessary. The model writes the chip labels,
    so a red flag can appear in an option the user tapped ("Blood in stool")
    while the original problem statement ("I have acidity") looks harmless. Every
    turn therefore scans the resolved labels the user actually selected, not just
    what they typed.

    Keyword matching over model-written text is best-effort, so it is the backstop
    for the planner's explicit `red_flag` markers rather than the only defence.
    """
    return any(is_emergency(fragment) for fragment in fragments if fragment)


# ---------------------------------------------------------------------------
# RULE 2 BACKSTOP — pharmaceuticals and dosages in a generated answer.
#
# Rule 2 in prompts.py was widened to permit Ayurvedic HERBS by name, because the
# GraphRAG graph's whole value is its herb relationships. That widening needs a
# guard, and until now rule 2 had NONE: no runtime check, and not one of
# test_safety.py's checks mentioned a medicine. It was enforced by prompt text
# alone, which is a instruction to a model, not a property of the system.
#
# This is a BACKSTOP, in the same sense `scan` is: keyword matching over
# model-written text is best-effort. It reports; it does not rewrite or block. A
# regex must never silently delete part of a health answer, and a false positive
# on "20 minutes of yoga" would do exactly that if it were allowed to.
# ---------------------------------------------------------------------------
import re as _re

# Pharmaceutical forms, common OTC drug names and brands. NOT herbs: Ashwagandha,
# Triphala, Tulsi and the rest are deliberately absent, since naming those is now
# permitted.
_DRUG_WORDS = _re.compile(
    r"\b(tablet|tablets|capsule|capsules|syrup|injection|antacid|antibiotic|"
    r"omeprazole|pantoprazole|ranitidine|paracetamol|ibuprofen|metformin|"
    r"eno|gelusil|digene|crocin|dolo)\b",
    _re.IGNORECASE,
)

# A quantity attached to a substance. Time and counts are deliberately excluded -
# "20 minutes", "8 glasses of water" and "2 times a day" are lifestyle guidance,
# not a dose. What is caught is a MASS or VOLUME, which is only ever a dosage.
_DOSAGE = _re.compile(
    r"\b\d+(?:\.\d+)?\s*(mg|mcg|ml|gram|grams|gm|g)\b"
    r"|\b\d+\s*(?:x|times)?\s*(?:tablet|capsule|tsp|teaspoon|tablespoon|tbsp)s?\b",
    _re.IGNORECASE,
)


def names_medicine(text: str) -> str:
    """The first drug name or dosage found in `text`, or "" if it is clean.

    Returns the offending phrase rather than a bool so the caller can log what
    was actually said - "it named something" is not actionable, "it said 500mg"
    is.
    """
    body = text or ""
    for pattern in (_DRUG_WORDS, _DOSAGE):
        found = pattern.search(body)
        if found:
            return found.group(0)
    return ""


# A drug named as the CAUSE of what the person is complaining about.
#
# A different failure from `names_medicine`, and a worse one. That one catches
# a medicine being recommended; this catches one being blamed. Rule 2 forbids
# telling someone to stop a prescribed drug, and for a while nothing forbade
# the sentence that actually makes them stop it — produced live and shown to a
# user, in a plan for acidity written for somebody on metformin:
#
#     "Metformin lene ke baad ... acidity mehsoos hona ek common baat ho sakti
#      hai ... metformin ka sevan ... is acidity aur jalan ka karan ho sakta hai"
#
# Hedged the whole way through, and the reader still hears "my tablet is doing
# this to me".
#
# WINDOWED, not whole-text: the plan legitimately mentions the drug ("aap
# metformin le rahe hain, isliye dhyan rakhna hoga") and separately uses causal
# words about diet and timing. Only a causal phrase NEAR the drug name is a
# finding. 90 characters is about one clause either side.
_CAUSAL_WORDS = _re.compile(
    r"\b(?:wajah|wajeh|karan|kaaran|karann|because|cause[sd]?|causing|due\s+to"
    r"|leads?\s+to|led\s+to|responsible|trigger(?:s|ed|ing)?|side\s*effect"
    r"|asar|prabhav|vajah)\b"
    r"|(?:की\s*वजह|कारण|दुष्प्रभाव)"
    # "X lene ke baad ye hota hai" carries no causal WORD at all and is the
    # commonest way this is actually phrased — it was the exact sentence that
    # reached a user. Anchored to a taking/starting verb on purpose: a bare
    # "ke baad" would fire on "khane ke baad", which is ordinary diet advice.
    r"|\b(?:lene|leni|liye|shuru\s+karne|start\s+karne)\s+ke\s+baad\b"
    r"|\bafter\s+(?:taking|starting|you\s+start)\b"
    r"|(?:लेने|शुरू\s*करने)\s*के\s*बाद",
    _re.IGNORECASE,
)
_BLAME_WINDOW = 90


def blames_medicine(text: str) -> str:
    """A quote where a drug is named as the cause, or "" when clean.

    Reports; never rewrites — the same contract `names_medicine` has, and for
    the reason `responder._warn_if_medicine` states: a regex silently deleting
    part of a health answer is a worse failure than the one it prevents. The
    prevention is `prompts.PERSONA_CORE` rule 2; this is how we find out when
    that did not hold.
    """
    body = text or ""
    for drug in _DRUG_WORDS.finditer(body):
        start = max(0, drug.start() - _BLAME_WINDOW)
        end = min(len(body), drug.end() + _BLAME_WINDOW)
        window = body[start:end]
        if _CAUSAL_WORDS.search(window):
            return window.strip()
    return ""
