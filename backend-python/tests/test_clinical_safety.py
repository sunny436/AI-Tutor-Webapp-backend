"""
P0-3 / P1-2: triage ladder, interaction checks and the recommendation gate.

DETERMINISTIC, and that is the point. Every rule here has to hold on the day
the model is rate-limited, wrong, or unreachable — the same reason
`test_safety.py` is a unit suite. Nothing in this file calls a model.

The negatives matter as much as the positives. A triage ladder that grades
ordinary indigestion as ORANGE is an assistant that sounds alarmed about
everything, and a gate that blocks safe advice is a gate that gets switched off.

    python tests/test_clinical_safety.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from src.clinical import gate, interactions  # noqa: E402
from src.clinical.triage import assess, strongest  # noqa: E402
from src.consult.sections import resolve_sections  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# ===========================================================================
# 1. The ladder
# ===========================================================================
check("levels order weakest to strongest", strongest("GREEN", "RED") == "RED")
check("an unknown level never outranks a known one", strongest("YELLOW", "nonsense") == "YELLOW")

GREEN_CASES = [
    ["mujhe acidity ho rahi hai"],
    ["baal jhad rahe hain"],
    ["gas aur bloating hoti hai"],
    ["thodi ulti ho rahi hai"],          # vomiting ALONE is not an emergency
    ["neend achhi nahi aati"],
]
for frags in GREEN_CASES:
    t = assess(frags)
    check(f"ordinary complaint stays GREEN: {frags[0][:34]!r}",
          t.risk_level == "GREEN", f"{t.risk_level} {t.triggering_features}")

RED_CASES = [
    (["seene me tez dard aur saans nahi aa rahi"], "chest pain with breathlessness"),
    (["I am vomiting 5+ times a day and cannot keep fluids down"], "vomiting, no fluids"),
    (["ulti ho rahi hai", "pani bhi nahi ruk raha"], "same, in Hinglish"),
    (["ulti me khoon aa raha hai"], "blood in vomit"),
]
for frags, label in RED_CASES:
    t = assess(frags)
    check(f"RED: {label}", t.risk_level == "RED", t.risk_level)
    check(f"...and normal chat stops: {label}",
          not t.can_continue_normal_chat and t.needs_immediate_escalation)

check("a symptom running for months is ORANGE, not GREEN",
      assess(["ye problem 3 mahine se hai aur theek nahi ho raha"]).risk_level == "ORANGE")
check("unexplained weight loss is ORANGE",
      assess(["mera wazan kam ho raha hai"]).risk_level == "ORANGE")
check("a lump is ORANGE", assess(["gale me ek ganth hai"]).risk_level == "ORANGE")

# CONTEXT COMES FROM THE PROFILE, not only from this turn's words — a
# pregnancy or a blood thinner disclosed months ago still counts today.
check("a chronic condition on the profile raises an ordinary complaint to YELLOW",
      assess(["mujhe acidity hai"], profile_conditions=["diabetes"],
             profile_medications=["metformin"]).risk_level == "YELLOW")
check("pregnancy on the profile raises it to ORANGE",
      assess(["mujhe acidity hai"], profile_conditions=["pregnant"]).risk_level == "ORANGE")
check("a diagnosed serious condition is never GREEN",
      assess(["mujhe acidity hai"], serious_condition="blood cancer").risk_level == "ORANGE")

# THE MODEL MAY RAISE AND MAY NEVER LOWER. The failure this prevents is a
# confidently reassuring model talking the system down off a flag it found.
check("the model can RAISE the level",
      assess(["mujhe acidity hai"], model_level="ORANGE").risk_level == "ORANGE")
check("the model can NEVER lower a deterministic finding",
      assess(["mera wazan kam ho raha hai"], model_level="GREEN").risk_level == "ORANGE")
check("the model cannot lower an emergency",
      assess(["ulti me khoon aa raha hai"], model_level="GREEN").risk_level == "RED")

# Missing safety information is only chased once there is a reason to.
check("nothing is demanded on GREEN ground",
      assess(["mujhe acidity hai"]).missing_safety_information == [])
check("above GREEN, unanswered safety questions are named",
      "age" in assess(["mera wazan kam ho raha hai"]).missing_safety_information)

check("the verdict is fully auditable",
      set(assess(["mujhe acidity hai"]).as_dict()) == {
          "risk_level", "triggering_features", "reason", "missing_safety_information",
          "recommended_action", "can_continue_normal_chat", "needs_immediate_escalation"})


# ===========================================================================
# 2. Interaction checks
# ===========================================================================
BLOCKED = [
    ("ashwagandha", {"medications": ["thyronorm"]}, "thyroid medication"),
    ("guggulu", {"medications": ["warfarin"]}, "a blood thinner"),
    ("fasting", {"medications": ["insulin"]}, "insulin"),
    ("panchakarma", {"conditions": ["pregnant"]}, "pregnancy"),
    ("licorice", {"conditions": ["hypertension"]}, "high blood pressure"),
    ("panchakarma", {"conditions": ["chronic kidney disease"]}, "kidney disease"),
]
for herb, facts, why in BLOCKED:
    v = interactions.check(herb, **facts)
    check(f"{herb} is BLOCKED with {why}", v.blocked, f"{v.status} {v.reasons}")

CAUTION = [
    ("fenugreek", {"medications": ["metformin"]}, "glucose-lowering medication"),
    ("turmeric", {"medications": ["warfarin"]}, "a blood thinner"),
    ("trikatu", {"medications": ["amlodipine tablet"]}, "any other medicine"),
]
for herb, facts, why in CAUTION:
    v = interactions.check(herb, **facts)
    check(f"{herb} is CAUTION with {why}", v.status == "caution", f"{v.status} {v.reasons}")

# A DRUG THEY STOPPED MUST NOT DRIVE A WARNING. This is what `Fact.status` and
# `PatientProfile.active(...)` are for; callers pass the active list.
check("a stopped medicine does not block a herb",
      not interactions.check("ashwagandha", medications=[]).blocked)

check("an allergy to the herb itself always blocks",
      interactions.check("turmeric", allergies=["turmeric"]).blocked)

check("an unknown herb is not blocked on a guess",
      interactions.check("shatavari", medications=["metformin"]).status == "safe")

# UNANSWERED IMPORTANT QUESTIONS ARE THEMSELVES A REASON TO PAUSE.
v = interactions.check("ashwagandha")
check("an unanswered pregnancy question downgrades to caution",
      v.status == "caution" and v.missing_information, v.as_dict())

check("screening finds every intervention an answer names",
      set(interactions.find_interventions(
          "Ashwagandha lijiye, haldi daaliye, aur upvas rakhiye"))
      == {"ashwagandha", "turmeric", "fasting"},
      interactions.find_interventions("Ashwagandha lijiye, haldi daaliye, aur upvas rakhiye"))


# ===========================================================================
# 3. The recommendation gate
# ===========================================================================
PLAN = """Samajh gaya, aapko acidity hai.

**Root Cause**
Pitta badha hua hai.

**Changes To Make**
Do: samay par khana khaiye.

**Yoga & Breathing**
Asanas: Vajrasana, Pawanmuktasana.

**Food Chart**
Eat: moong dal, khichdi.

**When To See A Doctor**
Ulti me khoon aaye to turant doctor ko dikhaiye."""

# THE MEASURED REGRESSION. Asking for one section and receiving the whole plan
# was ~1 turn in 3 once retrieval got richer, and no prompt wording fixed it.
r = gate.screen(PLAN, wanted_sections=resolve_sections(["yoga"]))
kept = [h for h, _b in gate.split_sections(r.answer) if h]
check("'sirf yoga batao' keeps only yoga (and the doctor section)",
      kept == ["Yoga & Breathing", "When To See A Doctor"], kept)
check("...and says which sections it removed",
      set(r.dropped_sections) == {"Root Cause", "Changes To Make", "Food Chart"},
      r.dropped_sections)
check("the opening sentence is kept, so the reader is still answered",
      "Samajh gaya" in r.answer)

r = gate.screen(PLAN, wanted_sections=resolve_sections(["food"]))
check("'sirf diet batao' keeps only the food chart",
      [h for h, _b in gate.split_sections(r.answer) if h]
      == ["Food Chart", "When To See A Doctor"])

r = gate.screen(PLAN, wanted_sections=resolve_sections(None))
check("a complete plan is left entirely alone", r.dropped_sections == [], r.dropped_sections)

# "When To See A Doctor" is ALWAYS_INCLUDED and must survive every scoping.
for pick in (["yoga"], ["food"], ["root_cause"], ["changes"]):
    r = gate.screen(PLAN, wanted_sections=resolve_sections(pick))
    check(f"the doctor section survives a {pick[0]!r}-only request",
          "When To See A Doctor" in r.answer, pick)

# Prose with no headings is not a plan and must not be touched.
prose = "Ayurveda mein agni ka matlab paachan shakti hai."
check("a conversational reply is left untouched",
      gate.screen(prose, wanted_sections=resolve_sections(["yoga"])).answer == prose)

# --- who is reading it -----------------------------------------------------
UNSAFE = """**Changes To Make**
Do: Ashwagandha raat ko lijiye. Do: samay par khana khaiye. Do: hafte me ek din upvas rakhiye.

**When To See A Doctor**
Chakkar aaye to dikhaiye."""

r = gate.screen(UNSAFE, medications=["thyronorm", "insulin"], conditions=["diabetes"])
check("a herb that clashes with their medication is removed",
      "shwagandha" not in r.answer, r.answer[:90])
check("fasting is removed for someone on insulin", "upvas" not in r.answer, r.answer[:90])
check("the safe advice in the same section survives",
      "samay par khana" in r.answer, r.answer[:120])
check("the reader is told something was withheld",
      "jaan-bujhkar nahi likhi" in r.answer, r.answer[-120:])
check("both blocks are recorded for the audit trail",
      {b["intervention"] for b in r.blocked_interventions} == {"ashwagandha", "fasting"},
      r.blocked_interventions)

check("the same plan is untouched for someone with none of those facts",
      "shwagandha" in gate.screen(UNSAFE).answer)

# --- the ceiling the triage level sets -------------------------------------
check("RED approves nothing at all", not gate.screen(PLAN, risk_level="RED").approved)
r = gate.screen(UNSAFE, risk_level="ORANGE")
check("ORANGE withdraws interventions even when none is individually unsafe",
      "shwagandha" not in r.answer and "upvas" not in r.answer, r.answer[:100])
check("ORANGE still allows education and low-risk lifestyle",
      {"EDUCATION", "LOW_RISK_LIFESTYLE"} <= set(r.allowed_categories))
check("GREEN allows an Ayurveda intervention",
      "AYURVEDA_INTERVENTION" in gate.allowed_categories("GREEN"))
check("ORANGE does not", "AYURVEDA_INTERVENTION" not in gate.allowed_categories("ORANGE"))

check("the gate result is fully auditable",
      {"approved", "allowed_categories", "dropped_sections", "blocked_interventions",
       "cautioned_interventions", "notes"} == set(gate.screen(PLAN).as_dict()))


# ===========================================================================
# 4. THE ASSISTANT MUST NOT ESCALATE AT ITS OWN WORDS
#
# Every plan ends with a "When To See A Doctor" section that names red flags
# ("khoon aaye to...", "seene me dard ho to..."), and that plan is stored in
# `chat_history`. `safety_fragments` fed the WHOLE transcript to `safety.scan`,
# so the next turn found those words in the assistant's own text and escalated
# — meaning any follow-up after receiving a plan became "go to hospital now".
#
# The same trap `is_serious_condition` has always documented; only
# `user_fragments` was guarded against it.
# ===========================================================================
from src.consult.schema import ChatTurn, ConsultContext  # noqa: E402
from src.consult.state import safety_fragments, user_fragments  # noqa: E402
from src import safety as _safety  # noqa: E402

PLAN_WITH_RED_FLAGS = (
    "Samajh gaya, aapko acidity hai.\n\n"
    "**When To See A Doctor**\n"
    "Ulti me khoon aaye ya seene me dard ho to turant doctor ko dikhaiye."
)
after_plan = ConsultContext(
    problem="acidity", condition="Acidity",
    chat_history=[
        ChatTurn(role="user", text="mujhe acidity hai"),
        ChatTurn(role="assistant", text=PLAN_WITH_RED_FLAGS),
        ChatTurn(role="user", text="theek hai, dhanyavaad"),
    ],
)
frags = safety_fragments(after_plan)
check("the assistant's own plan is NOT scanned for red flags",
      not any("khoon" in f for f in frags), [f[:50] for f in frags if "khoon" in f])
check("...so an innocent follow-up after a plan does not escalate",
      not _safety.scan(*frags), frags)
check("the user's own turns ARE still scanned", any("acidity" in f for f in frags))

# ...and a REAL red flag the user types still fires, from any turn.
real = ConsultContext(
    problem="acidity",
    chat_history=[
        ChatTurn(role="user", text="mujhe acidity hai"),
        ChatTurn(role="assistant", text=PLAN_WITH_RED_FLAGS),
        ChatTurn(role="user", text="ab ulti me khoon aa raha hai"),
    ],
)
check("A REAL RED FLAG TYPED LATER STILL ESCALATES",
      _safety.scan(*safety_fragments(real)),
      [f[:40] for f in safety_fragments(real)])
check("user_fragments is unaffected — it was already guarded",
      not any("khoon aaye ya seene" in f for f in user_fragments(after_plan)))


# ===========================================================================
# 5. THE HEADING THE MODEL ACTUALLY WROTE
#
# THIS IS THE FIX FOR THE test_intake FOCUS FLAKE, and it is deterministic on
# purpose: the flake was a live-model test noticing, occasionally, that the
# gate only recognised ONE spelling of a heading. Three others were produced
# in real runs, and each failed differently:
#
#   "**Root Cause:**"        colon INSIDE the asterisks -> matched nothing in
#                            the library, so EVERY section was dropped and the
#                            reader got a plan with no content at all.
#   "## Root Cause"          not the bold form -> nothing recognised, nothing
#                            dropped: the section leak the flake reported.
#   "**Yoga and Breathing**" "and" for "&" -> the one section the reader had
#                            explicitly asked for was the one thrown away.
#
# Making the live test tolerant would have hidden all three. The gate is what
# had to change, so the variants are pinned here where no model is involved.
# ===========================================================================
YOGA_ONLY = ["yoga"]
HEADING_VARIANTS = [
    ("the canonical form the prompt asks for",
     "**Root Cause**\nPitta.\n\n**Yoga & Breathing**\nVajrasana.\n\n"
     "**Food Chart**\nMoong dal."),
    ("a colon inside the asterisks",
     "**Root Cause:**\nPitta.\n\n**Yoga & Breathing:**\nVajrasana.\n\n"
     "**Food Chart:**\nMoong dal."),
    ("a colon after the asterisks",
     "**Root Cause**:\nPitta.\n\n**Yoga & Breathing**:\nVajrasana."),
    ("markdown hash headings",
     "## Root Cause\nPitta.\n\n## Yoga & Breathing\nVajrasana.\n\n"
     "## Food Chart\nMoong dal."),
    ('"and" written out instead of "&"',
     "**Root Cause**\nPitta.\n\n**Yoga and Breathing**\nVajrasana.\n\n"
     "**Food Chart**\nMoong dal."),
    ("a trailing space after the heading",
     "**Root Cause** \nPitta.\n\n**Yoga & Breathing** \nVajrasana."),
]
for label, written in HEADING_VARIANTS:
    kept, dropped = gate.enforce_sections(written, YOGA_ONLY)
    check(f"the section the reader ASKED FOR survives: {label}",
          "**Yoga & Breathing**" in kept and "Vajrasana" in kept, kept[:70])
    check(f"...and the ones they did not ask for are gone: {label}",
          "Root Cause" not in kept and "Food Chart" not in kept, kept[:70])
    check(f"...and the kept heading is rewritten to the canonical form: {label}",
          kept.count("**Yoga & Breathing**") == 1, kept[:70])

# A HASH LINE THAT IS NOT A KNOWN SECTION IS NOT A SECTION BOUNDARY. Treating
# it as one would let this function delete text nobody asked it to touch.
kept, dropped = gate.enforce_sections(
    "Namaste.\n\n## Kuch aur baatein\nye zaroori hai.\n\n"
    "**Yoga & Breathing**\nVajrasana.", YOGA_ONLY)
check("an unrecognised hash line is left alone, not dropped",
      "ye zaroori hai" in kept and not dropped, f"{dropped} {kept[:60]}")

# AND THE EMPTY-PLAN FAILURE ITSELF, pinned directly: whatever the spelling,
# enforcing a section the answer contains must never return an answer with no
# sections at all.
for label, written in HEADING_VARIANTS:
    kept, _dropped = gate.enforce_sections(written, YOGA_ONLY)
    check(f"enforcement never empties a plan that HAS the section: {label}",
          len(kept.strip()) > 20, repr(kept[:40]))

# A conversational reply has no sections and must come back untouched.
chat = "Namaste, bataiye kya pareshani hai?"
check("a reply with no headings is returned unchanged",
      gate.enforce_sections(chat, YOGA_ONLY) == (chat, []))


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== clinical safety: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}{f' [{detail}]' if detail else ''}")
sys.exit(0 if passed == len(results) else 1)
