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
    # PRESSURE AND TIGHTNESS, not only "pain". This is how people describe a
    # heart attack at least as often — "severe chest pressure and sweating" is
    # the spec's own emergency example, and the table did not hold it.
    "chest pressure", "pressure in my chest", "chest tightness",
    "tightness in my chest", "chest heaviness", "heaviness in my chest",
    "seene me dabav", "seene mein dabav", "chhati me dabav",
    "seene me bhaari", "seene mein bhaari", "chhati bhaari",
    "seene me jakdan", "सीने में दबाव", "छाती में दबाव",
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

# GAPS FOUND BY THE SIMULATED-PATIENT BENCHMARK, not by a bug report.
#
# `tests/benchmark_patients.py` runs a population of emergency phrasings rather
# than a handful, and five of fifteen came back GREEN. Every one of them is a
# sentence a real user would type, and every one is an emergency:
#
#   "saans lene me bahut takleef ho rahi hai"   -> the list had "dikkat", not
#                                                  "takleef", for the same thing
#   "bahut zyada bleeding ho rahi hai"          -> only English "severe
#                                                  bleeding" was covered
#   "sudden weakness on one side of my body"    -> stroke; only "sudden
#                                                  numbness" was covered
#   "achanak bahut tez sar dard, sabse bura"    -> thunderclap headache; only
#                                                  English "severe headache"
#   "baccha 3 mahine ka hai aur tez bukhar"     -> fever in an infant
#
# The same lesson the Hinglish block above records, one layer further in: it is
# not enough to cover the concept once in English, because the phrase people
# reach for varies and a substring match does not generalise.
RED_FLAG_KEYWORDS += [
    # breathing — "takleef"/"pareshani" as well as "dikkat"
    "saans lene me takleef", "saans lene mein takleef",
    "saans lene me bahut takleef", "saans me takleef", "saans mein takleef",
    "saans lene me pareshani", "saans ukhad", "haanf raha",
    "साँस लेने में तकलीफ", "सांस लेने में तकलीफ",
    # bleeding — Hinglish intensifiers
    "zyada bleeding", "bahut bleeding", "bleeding ho rahi", "bleeding nahi ruk",
    "khoon nahi ruk", "bahut khoon", "khoon bahut",
    "खून नहीं रुक", "बहुत खून",
    # stroke — weakness or drooping on one side
    "weakness on one side", "one side of my body", "one side of the body",
    "ek taraf kamzori", "ek side kamzori", "adha sharir", "aadha sharir",
    "half of my body", "muh tedha", "face tedha",
    "एक तरफ कमज़ोरी", "आधा शरीर",
    # thunderclap / worst-ever headache
    "worst headache", "sabse tez sar dard", "sabse bura sar dard",
    "achanak tez sar dard", "achanak bahut tez sar dard",
    "sar phat raha", "sar fat raha",
    "सबसे तेज़ सिरदर्द", "अचानक तेज़ सिरदर्द",
    # infant illness — an age, not a symptom, but decisive at this age
    "newborn", "naya janma", "mahine ka baccha", "mahine ki bacchi",
    "din ka baccha", "navjat",
    # stroke — said as FUNCTION rather than as "weakness". "ek side ka haath
    # kaam nahi kar raha" is the sentence people actually type, and none of
    # the "kamzori" entries above match it. Narrow on purpose: a side or
    # "achanak" is required, so chronic joint stiffness does not trip it.
    "ek side ka haath kaam nahi", "ek taraf ka haath kaam nahi",
    "ek side ka pair kaam nahi", "ek taraf ka pair kaam nahi",
    "ek side kaam nahi kar raha", "ek taraf kaam nahi kar raha",
    "achanak haath kaam nahi", "achanak pair kaam nahi",
    "one side is not working", "one side stopped working",
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


# A DISEASE NAMED INSIDE A FEAR IS NOT A DIAGNOSIS.
#
#     "mujhe darr lagta hai ki kahin cancer to nahi"
#
# is a worried person with acidity, and the keyword put them into the
# serious-condition pathway: supportive care, no plan, and an answer to a
# question they never asked. prompts.py has carried this rule for the model
# since the intake fix ("A DISEASE NAMED INSIDE A QUESTION IS NOT A
# DISCLOSURE"); the deterministic layer did not, so the keyword silently
# overruled the model.
#
# The frame has to be recognised NARROWLY, because the cost of getting it
# wrong in the other direction is missing a real disclosure. Both halves are
# required: a worry word BEFORE the disease, and a hedge closing it AFTER.
#
#     "mujhe cancer hai, darr lagta hai"        -> disclosure (no worry BEFORE)
#     "mujhe cancer hai, kya yoga kar sakta hoon?" -> disclosure (same)
#     "kya mujhe cancer hai?"                   -> question
#     "kahin cancer to nahi"                    -> question
_WORRY_BEFORE = ("kahin", "shayad", "darr", "dar lagta", "kya", "could",
                 "might", "maybe", "afraid", "worried", "scared", "lagta hai ki",
                 "कहीं", "शायद", "डर", "क्या")
_HEDGE_AFTER = ("to nahi", "to nahin", "to na ", "?", "तो नहीं", "hai kya")


def _is_hypothetical(lowered: str, start: int, end: int) -> bool:
    """Is the disease named at [start:end] a worry rather than a disclosure?"""
    before = lowered[max(0, start - 40):start]
    after = lowered[end:end + 30]
    return (any(w in before for w in _WORRY_BEFORE)
            and any(h in after for h in _HEDGE_AFTER))


def is_serious_condition(text: str) -> bool:
    """A diagnosed condition this assistant must not build a wellness plan for."""
    lowered = (text or "").lower()
    return any(not _is_hypothetical(lowered, m.start(), m.end())
               for m in _SERIOUS_RE.finditer(lowered))


# ASKING FOR YOGA IS NOT ASKING TO STOP CHEMOTHERAPY, and the difference is the
# whole of this function.
#
# Someone on treatment who asks "can you suggest some yoga" wants supportive
# movement ALONGSIDE their care. Someone who asks "chemo band karke ayurveda le
# lun?" wants to replace it. The first needs a gentle answer and a symptom
# check; the second needs the displacement warning. Answering both with the
# same paragraph is what produced the loop reported from production — the
# warning was correct, and it was also the only thing the person ever got, on
# every turn, however they rephrased.
#
# So the warning is attached to the REQUEST, not to the diagnosis. Narrow on
# purpose: a replacement verb aimed at treatment, or an explicit swap phrase.
_TREATMENT = (r"chemo\w*|kimo|radiation|radio\s*therapy|dialysis|insulin"
              r"|treatment|ilaj|ilaaj|chikitsa|dawa|dawai|medicine|therapy"
              r"|tablet|goli")
_REPLACE_VERB = (r"band\s*kar|bnd\s*kar|chhod|chod|stop|quit|replace|instead"
                 r"|skip|rok\s*d|ruk\s*ja|leave|discontinue|off\s*kar")
_REPLACE_RE = re.compile(
    # "chemo band kar dun", "stop my chemotherapy", "chemo chhod kar yoga"
    rf"\b(?:{_TREATMENT})\b[^.?!]{{0,30}}?\b(?:{_REPLACE_VERB})"
    rf"|\b(?:{_REPLACE_VERB})\w*\b[^.?!]{{0,30}}?\b(?:{_TREATMENT})\b"
    # "yoga se theek ho jayega?", "ayurveda ki jagah", "instead of chemo"
    rf"|\b(?:ki|ke)\s*(?:jagah|badle|bajay)\b"
    rf"|\binstead\s+of\b"
    rf"|\bonly\s+(?:yoga|ayurveda|herbs?)\b",
    re.IGNORECASE,
)


def asks_to_replace_treatment(text: str) -> bool:
    """Is this asking to STOP or SWAP a prescribed treatment, not add to it?"""
    return bool(_REPLACE_RE.search(text or ""))


# The message we show when a red flag is found.
ESCALATION_MESSAGE = (
    "⚠️ **Please seek medical help right away.**\n\n"
    "What you described may be serious. Please contact a doctor immediately or "
    "call your local emergency number / go to the nearest hospital.\n\n"
    "For your safety, I am not giving wellness advice for this. Your health "
    "comes first — please get medical care now."
)


# Practices a safety reply must not put in front of somebody who has just been
# told to go to a doctor.
#
# WHY THE CATEGORY WORDS ARE HERE TOO. "pranayama" and "asana" are generic in
# Hinglish — "koi pranayama na karein" means "do not do any breathing
# exercise", which is a PROHIBITION and perfectly good advice. But a reader
# skimming an alarming message takes the words they recognise, and a sentence
# containing "pranayama" is one misreading away from being taken as a
# suggestion. In an emergency reply the plain words ("yoga", "breathing
# exercises") say the same thing with no such edge, so the Sanskrit terms are
# simply not used. Cheap, and it removes the ambiguity entirely.
_PRACTICE_WORDS = (
    # named practices — actionable, and the real danger
    "vajrasana", "pawanmuktasana", "pavanmuktasana", "bhujangasana",
    "shavasana", "savasana", "balasana", "ushtrasana", "dhanurasana",
    "setu bandha", "matsyendrasana", "halasana", "sarvangasana",
    "anulom", "anulom vilom", "nadi shodhan", "kapalbhati", "kapalabhati",
    "bhastrika", "bhramari", "shitali", "sheetali", "sheetkari",
    "surya namaskar", "suryanamaskar",
    # category words — see above
    "pranayama", "pranayam", "asana", "aasana",
)


def names_practice(text: str) -> str:
    """The first yoga/breathing practice named in `text`, or "" if clean.

    Used by `responder.write_safety_first` to check its own output. Returns the
    word rather than a bool so the retry can quote it back.
    """
    lowered = (text or "").lower()
    return next((w for w in _PRACTICE_WORDS if w in lowered), "")


# ---------------------------------------------------------------------------
# SCRIPT MIXING. A transliteration keyboard produces half-Devanagari sentences,
# and they are extremely common here:
#
#     "ulti me खून aa raha hai"          -> Latin list wants "khoon"
#     "baby ko तेज बुखार hai"             -> Latin list wants "bukhar"
#     "मेरे एक side का हाथ काम नहीं कर रहा"  -> neither list matches at all
#
# Every one of those was missed while the pure-Latin and pure-Devanagari
# versions of the same sentence were caught, which left the person typing in
# mixed script the LEAST protected. Exactly backwards.
#
# So a small map folds the decisive Devanagari medical words to the Hinglish
# spelling the Latin table already uses, and the scan runs over both forms.
# This is a spelling bridge for high-signal words, not a transliterator: every
# entry here is a word whose presence changes the safety decision, because a
# wrong entry costs a false alarm.
_DEVANAGARI_TO_HINGLISH = {
    "खून": "khoon", "उल्टी": "ulti", "बुखार": "bukhar", "सीने": "seene",
    "छाती": "chaati", "दर्द": "dard", "साँस": "saans", "सांस": "saans",
    "बेहोश": "behosh", "तेज़": "tez", "तेज": "tez", "सिरदर्द": "sir dard",
    "सिर": "sir", "कमज़ोरी": "kamzori", "कमजोरी": "kamzori", "एक": "ek",
    "तरफ": "taraf", "आधा": "aadha", "शरीर": "sharir", "हाथ": "haath",
    "पैर": "pair", "काम": "kaam", "नहीं": "nahi", "में": "me", "का": "ka",
    "महीने": "mahine", "हफ्ते": "hafte", "बच्चा": "baccha", "बच्चे": "bacche",
    "बच्ची": "bacchi", "नवजात": "navjat", "मल": "mal", "शौच": "shauch",
    "निकल": "nikal", "रुक": "ruk", "बहुत": "bahut", "अचानक": "achanak",
    "सबसे": "sabse", "बुरा": "bura", "फट": "phat", "तकलीफ": "takleef",
    "लेने": "lene", "मिर्गी": "mirgi", "खुदकुशी": "khudkushi",
    "आत्महत्या": "aatmahatya", "दौरा": "daura", "उल्टियाँ": "ultiyan",
}


def _fold_scripts(lowered: str) -> str:
    for devanagari, hinglish in _DEVANAGARI_TO_HINGLISH.items():
        if devanagari in lowered:
            lowered = lowered.replace(devanagari, hinglish)
    return lowered


# INFANT AGE, written either way round and in either script once folded.
# A plain "month old" substring was the obvious shortcut and it is wrong:
# "my 2 week old headache" would have become an emergency. Both an age AND a
# word for a child are required, within sight of each other.
_AGE = r"\d{1,2}\s*(?:month|months|week|weeks|day|days|mahine|mahina|hafte|din)"
_CHILD = (r"(?:baby|babies|baccha|bacche|bachcha|bachche|bacchi|bachchi|"
          r"newborn|navjat|infant|shishu)")
_INFANT_RE = re.compile(
    rf"{_AGE}[^.!?\n]{{0,40}}{_CHILD}|{_CHILD}[^.!?\n]{{0,40}}{_AGE}",
    re.IGNORECASE,
)


# AND A SYMPTOM, not the age alone. A three-month-old with gas needs a
# paediatrician, not an ambulance, and grading that RED is how a parent learns
# to ignore the warning. The age is what turns an ordinary-sounding symptom
# into an emergency, so both halves are required here.
_INFANT_SYMPTOM = re.compile(
    r"bukhar|fever|temperature|saans|breath|dood[h]?\s*nahi|feed(?:ing)?\s*nahi"
    r"|not\s+feeding|sust|lethargic|jhatk|fits|daur[ae]|convuls|ulti|vomit"
    r"|khoon|blood|dast|diarrh|dehydrat|pani\s+nahi|rota\s+nahi|neel[ai]|blue"
    r"|jaag\s*nahi|beh(?:o|ō)sh|nahi\s+uth",
    re.IGNORECASE,
)


# AN INTENSIFIER BETWEEN THE WORDS BREAKS A SUBSTRING MATCH.
#
# The list above holds "seene me dard", and people write "seene me TEZ dard".
# Found by the PHASE-7 evaluation: "मुझे सीने में तेज़ दर्द हो रहा है" — chest
# pain, stated plainly — matched no keyword and graded GREEN on the triage
# ladder too. It escalated nowhere at all.
#
# Adding every permutation to a substring list is whack-a-mole, so the few
# red flags that are BODY-PART + PAIN get a pattern that tolerates the words
# people put in the middle. Deliberately small: only the concepts where an
# intervening adjective is common and the miss is dangerous.
_GAP = r"[^.?!\n]{0,18}"
_RED_FLAG_PATTERNS = (
    # chest pain / pressure, with or without an intensifier between
    re.compile(r"\b(seene|seene?\s*mein?|chhati|chaati|chest)\b" + _GAP
               + r"\b(dard|pain|dabav|pressure|jakdan|bhaari|heaviness|tightness)\b",
               re.IGNORECASE),
    # breathlessness with something between ("saans bilkul nahi aa rahi")
    re.compile(r"\bsaans\b" + _GAP + r"\b(nahi|nhi|band|ruk)\b", re.IGNORECASE),
    # blood in vomit/stool with an intervening word
    re.compile(r"\b(ulti|vomit|stool|latrine|potty|tatti|shauch)\b" + _GAP
               + r"\b(khoon|blood)\b", re.IGNORECASE),
)


def is_emergency(text: str) -> bool:
    """Return True if the message looks like a serious/emergency situation."""
    lowered = (text or "").lower()
    folded = _fold_scripts(lowered)
    if any(keyword in lowered or keyword in folded for keyword in RED_FLAG_KEYWORDS):
        return True
    # Patterns run on the FOLDED text too, so a Devanagari sentence is checked
    # by the same rule as its Latin equivalent.
    if any(p.search(lowered) or p.search(folded) for p in _RED_FLAG_PATTERNS):
        return True
    return bool(_INFANT_RE.search(folded) and _INFANT_SYMPTOM.search(folded))


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


# BLAME IS WIDER THAN NAMING. `_DRUG_WORDS` lists dosage forms and specific
# drugs, because that is what `names_medicine` must not let through. But rule 2
# is broken just as badly without naming anything:
#
#     "Aapki thyroid ki dawa hi is jalan ka karan hai"
#
# No brand, no dosage form, and the patient still hears "your prescription is
# what is hurting you" from us. So blame detection reads the generic words too.
# It can afford to, and `names_medicine` cannot: blame additionally requires a
# causal word inside the window, while `names_medicine` fires on the word alone
# and would flag every legitimate "apne doctor ki dawa jaari rakhiye".
_GENERIC_MEDICINE = (r"dawa|dawai|dawaai|davai|dava|dawaiyan|goli|goliyan"
                     r"|medicine|medicines|prescription|दवा|दवाई|गोली")
_MEDICINE_REFERENCES = _re.compile(
    "(?:" + _DRUG_WORDS.pattern + r")|\b(?:" + _GENERIC_MEDICINE + r")\b",
    _re.IGNORECASE,
)

# ONE LEGITIMATE PAIRING HAS TO SURVIVE. Warning that a herb can change how a
# prescribed medicine works is the opposite of blaming that medicine, and it is
# the exact wording of the supportive-care message we ship ("chal rahi dawa ka
# asar badha ya ghata deti hain"). Without this the guard fires on our own copy.
_INTERACTION_CAVEAT = _re.compile(
    r"asar\s+(?:badha|ghata|kam|zyada)|badha\s+ya\s+ghata"
    r"|interact|interaction|effect\s+of\s+(?:your|the)\s+medicine",
    _re.IGNORECASE,
)


def blames_medicine(text: str) -> str:
    """A quote where a drug is named as the cause, or "" when clean.

    Reports; never rewrites — the same contract `names_medicine` has, and for
    the reason `responder._warn_if_medicine` states: a regex silently deleting
    part of a health answer is a worse failure than the one it prevents. The
    prevention is `prompts.PERSONA_CORE` rule 2; this is how we find out when
    that did not hold.
    """
    body = text or ""
    for drug in _MEDICINE_REFERENCES.finditer(body):
        start = max(0, drug.start() - _BLAME_WINDOW)
        end = min(len(body), drug.end() + _BLAME_WINDOW)
        window = body[start:end]
        if _CAUSAL_WORDS.search(window) and not _INTERACTION_CAVEAT.search(window):
            return window.strip()
    return ""
