"""
The patient profile: merged correctly, used silently, never recited back.

Deterministic unit tests for `merge_profile` first — those rules are the ones
that decide whether a person's allergy survives — then live tests for the
conversation behaviour the profile exists to produce.

    python tests/test_patient_profile.py
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src import safety  # noqa: E402
from src.consult import run_turn  # noqa: E402
from src.consult.schema import PatientProfile  # noqa: E402
from src.consult.sections import SECTION_LIBRARY, looks_like_plan  # noqa: E402
from src.consult.state import merge_profile, render_profile  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


HEADINGS = [h for h, _ in SECTION_LIBRARY.values()]

# §1k — phrases that narrate the mechanism. Pattern-based, NOT a bare word
# ban: "koi recent reports hain?" asks for the patient's own documents and
# must pass, and "note" appears innocently in ordinary prose.
NARRATION = re.compile(
    r"(your|the|our|my)\s+(patient\s+)?profile"
    r"|patient\s+profile"
    r"|in\s+(our|the)\s+(records?|system|database)"
    r"|database"
    r"|already\s+noted|is\s+noted|have\s+noted"
    r"|on\s+file"
    r"|saved\s+(history|profile|information)"
    r"|(history|profile|information)\s+(saved|stored|recorded)"
    r"|stored\s+(history|profile|information)"
    r"|history\s+is\s+(loaded|saved|stored)"
    r"|according\s+to\s+your\s+(history|profile|record)"
    r"|aapki\s+profile|aapke\s+record",
    re.IGNORECASE,
)


def narration(text: str) -> list[str]:
    return [m.group(0) for m in NARRATION.finditer(text or "")]


# ===========================================================================
# 1. merge_profile — deterministic, no model.
# ===========================================================================
p = PatientProfile()
p, changed = merge_profile(p, {"age": "29", "conditions": ["diabetes"],
                               "medications": ["metformin"]})
check("new facts are added", changed and p.age == "29"
      and p.conditions == ["diabetes"] and p.medications == ["metformin"])

p, changed = merge_profile(p, {"age": "30"})
check("a corrected scalar REPLACES the old value", changed and p.age == "30",
      p.age)
check("correcting a scalar does not disturb the lists", p.conditions == ["diabetes"])

p, changed = merge_profile(p, {"conditions": ["hypertension"]})
check("a list merges rather than replacing",
      p.conditions == ["diabetes", "hypertension"], p.conditions)

p, changed = merge_profile(p, {"conditions": ["DIABETES"]})
check("a case-different duplicate is not re-added and reports no change",
      not changed and p.conditions == ["diabetes", "hypertension"], p.conditions)

p, changed = merge_profile(p, {"allergies": []})
check("SILENCE IS NOT RETRACTION — unmentioned facts survive",
      not changed and p.conditions == ["diabetes", "hypertension"], p.conditions)

p, changed = merge_profile(p, {}, removals={"medications": ["metformin"]})
check("an explicit contradiction removes the fact",
      changed and p.medications == [], p.medications)

p_over = PatientProfile()
p_over, _ = merge_profile(p_over, {"conditions": [f"c{i}" for i in range(30)]})
check("lists are bounded", len(p_over.conditions) <= 12, len(p_over.conditions))

check("an empty profile renders to nothing", render_profile(PatientProfile()) == "")
check("render_profile emits human labels, never field identifiers",
      not any(t in render_profile(p) for t in
              ("patient_profile", "family_history", "risk_level", "help_types", "_")),
      render_profile(p))
check("a fresh profile reports itself empty", PatientProfile().is_empty())


# ===========================================================================
# Live helpers
# ===========================================================================
async def turn(msg: str, ctx: dict | None = None, as_problem: bool = False):
    if ctx is None or as_problem:
        return await run_turn(problem=msg, raw_context=ctx, answers=None,
                              free_text=None, profile="")
    return await run_turn(problem="", raw_context=ctx, answers=None,
                          free_text=msg, profile="")


# ===========================================================================
# 2. Facts stated in passing are captured, and never asked for again.
# ===========================================================================
async def _test_capture_and_never_reask():
    r = await turn("mujhe diabetes hai aur metformin leta hoon, ab acidity ho rahi hai")
    ctx = r.context.model_dump()
    prof = ctx["patient_profile"]
    check("a condition volunteered in passing is captured",
          any("diabet" in c.lower() for c in prof["conditions"]), prof["conditions"])
    check("a medicine volunteered in passing is captured",
          any("metformin" in m.lower() for m in prof["medications"]), prof["medications"])
    check("the complaint is engaged with in the same turn, not deferred",
          any(w in (r.answer or "").lower() for w in ("acidity", "jalan", "pet")),
          (r.answer or "")[:120])
    check("the first reply does not narrate a profile", not narration(r.answer or ""),
          narration(r.answer or ""))

    # Two more turns: the known facts must not be asked for again.
    asked = []
    for msg in ("2 din se hai", "khaane ke baad zyada hoti hai"):
        r = await turn(msg, dict(ctx))
        ctx = r.context.model_dump()
        asked.append(r.answer or "")
    joined = " ".join(asked).lower()
    check("a known medicine is never asked for again",
          not re.search(r"kaun[sc]i\s+medicine|which\s+medicine|konsi\s+dawa", joined),
          joined[:160])
    check("no later reply narrates a profile",
          not narration(" ".join(asked)), narration(" ".join(asked)))


asyncio.run(_test_capture_and_never_reask())


# ===========================================================================
# 3. The profile survives a brand-new consultation in the same conversation.
# ===========================================================================
async def _test_survives_restart():
    r = await turn("mujhe diabetes hai, metformin chalti hai")
    ctx = r.context.model_dump()
    before = list(ctx["patient_profile"]["conditions"])
    check("PRECONDITION: something was captured", bool(before), before)

    r2 = await turn("ab mujhe baal jhadne ki problem hai", dict(ctx), as_problem=True)
    after = r2.context.model_dump()["patient_profile"]["conditions"]
    check("the profile survives a new complaint restarting the consultation",
          after == before, f"{before} -> {after}")


asyncio.run(_test_survives_restart())


# ===========================================================================
# 4. A serious diagnosis opens a clinical deep-dive, not a wellness plan.
# ===========================================================================
async def _test_serious_deep_dive():
    r = await turn("mujhe diabetes hai, metformin leta hoon")
    ctx = r.context.model_dump()

    replies = []
    for msg in ("mujhe cancer ho gaya hai", "blood cancer hai",
                "AML hai, chemotherapy chal rahi hai"):
        r = await turn(msg, dict(ctx))
        ctx = r.context.model_dump()
        replies.append(r.answer or "")

    check("the disclosure is recorded once, so the deep-dive can proceed",
          bool(ctx.get("serious_condition")), ctx.get("serious_condition"))
    check("cancer reaches the profile as a stated fact",
          any("cancer" in c.lower() for c in ctx["patient_profile"]["conditions"]),
          ctx["patient_profile"]["conditions"])
    check("NO wellness plan is produced while details are being collected",
          not any(h in a for a in replies for h in HEADINGS)
          and not any(looks_like_plan(a) for a in replies))
    check("no herb, drug or dose is offered during the deep-dive",
          not any(safety.names_medicine(a) for a in replies),
          [safety.names_medicine(a) for a in replies if safety.names_medicine(a)])
    check("the deep-dive does not repeat itself verbatim",
          len(set(replies)) == len(replies), f"{len(set(replies))} distinct of {len(replies)}")
    check("the deep-dive never narrates a profile",
          not any(narration(a) for a in replies),
          [narration(a) for a in replies if narration(a)])
    check("known diabetes is not re-asked during the deep-dive",
          not re.search(r"kya aapko (koi )?diabetes", " ".join(replies), re.IGNORECASE))


asyncio.run(_test_serious_deep_dive())


# ===========================================================================
# 5. The gate must not over-fire: an ordinary complaint still reaches a plan.
# ===========================================================================
async def _test_low_risk_still_reaches_a_plan():
    ctx = None
    msg = "mujhe khaana khane ke baad pet me jalan hoti hai"
    for _ in range(6):
        r = await turn(msg, ctx, as_problem=ctx is None)
        ctx = r.context.model_dump()
        if ctx.get("phase") == "asking_focus":
            break
        msg = "bas itna hi hai, aap bata dijiye"
    check("an ordinary complaint still reaches asking_focus",
          ctx.get("phase") == "asking_focus", ctx.get("phase"))
    if ctx.get("phase") != "asking_focus":
        return
    r = await turn("poora plan batao", dict(ctx))
    answer = r.answer or ""
    check("an ordinary complaint still gets a real plan",
          r.kind == "answer" and looks_like_plan(answer), r.kind)
    check("the final plan does not narrate a profile", not narration(answer),
          narration(answer))
    check("the final plan makes no deterministic prediction",
          not re.search(r"you will develop|aapko .* ho jayega", answer, re.IGNORECASE))


asyncio.run(_test_low_risk_still_reaches_a_plan())


# ===========================================================================
# 6. Legitimate recall and report questions must NOT trip the guard.
#    Guards the guard: a tighter pattern would suppress real doctor speech.
# ===========================================================================
check("asking for the patient's own reports is not narration",
      not narration("Kya aapke paas koi recent reports hain?"))
check("referring to what they told you is not narration",
      not narration("Aapne pehle diabetes ke baare mein bataya tha, isliye..."))
check("but announcing a stored profile IS caught",
      bool(narration("Your diabetes is already noted in your profile.")))
check("and announcing loaded history IS caught",
      bool(narration("I have your previous history saved.")))


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== patient profile: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, _ in results:
        if not ok:
            print(f"  - {name}")
sys.exit(0 if passed == len(results) else 1)
