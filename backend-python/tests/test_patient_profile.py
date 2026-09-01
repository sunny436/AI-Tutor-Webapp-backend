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

# Windows redirects stdout as cp1252, and several test NAMES below are
# Devanagari — so `print`ing a PASS raised UnicodeEncodeError and killed the
# run partway through. The suite could not be run to completion on the
# platform its own docstring tells you to run it on. Same reconfigure
# `server.py` applies, for the same reason.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


from src import safety  # noqa: E402
from src.consult import run_turn  # noqa: E402
from src.consult.schema import PatientProfile  # noqa: E402
from src.consult.sections import SECTION_LIBRARY, looks_like_plan  # noqa: E402
from src.consult.state import merge_profile, render_profile  # noqa: E402
from src import prompts as _prompts  # noqa: E402

# Read as TEXT, not imported: the assertion is that `run_turn` actually
# hands the removals on, and importing the function cannot show that.
_graph_source = (
    Path(__file__).resolve().parents[1] / 'src' / 'consult' / 'graph.py'
).read_text(encoding='utf-8')

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
# EVERY LIST NOW HOLDS `Fact`, not `str` — a value plus where it came from and
# when it was last true (schema.Fact, P0-1). `.values(key)` is the plain-word
# view; `.active(key)` is what is true NOW. The assertions below are the same
# assertions, read through those helpers — see tests/test_clinical_state.py for
# the provenance rules themselves.
p = PatientProfile()
p, changed = merge_profile(p, {"age": "29", "conditions": ["diabetes"],
                               "medications": ["metformin"]})
check("new facts are added", changed and p.age == "29"
      and p.values("conditions") == ["diabetes"]
      and p.values("medications") == ["metformin"])

p, changed = merge_profile(p, {"age": "30"})
check("a corrected scalar REPLACES the old value", changed and p.age == "30",
      p.age)
check("correcting a scalar does not disturb the lists",
      p.values("conditions") == ["diabetes"])

p, changed = merge_profile(p, {"conditions": ["hypertension"]})
check("a list merges rather than replacing",
      p.values("conditions") == ["diabetes", "hypertension"], p.values("conditions"))

p, changed = merge_profile(p, {"conditions": ["DIABETES"]})
check("a case-different duplicate is not re-added",
      p.values("conditions") == ["diabetes", "hypertension"], p.values("conditions"))

p, changed = merge_profile(p, {"allergies": []})
check("SILENCE IS NOT RETRACTION — unmentioned facts survive",
      not changed and p.values("conditions") == ["diabetes", "hypertension"],
      p.values("conditions"))

p, changed = merge_profile(p, {}, removals={"medications": ["metformin"]})
# RETRACTION IS NOW A STATUS CHANGE, NOT A DELETE, and this is a STRONGER
# assertion than the one it replaces. What mattered was "the stopped drug is
# no longer treated as current" — that is `active(...) == []`. Deleting the row
# also threw away the fact that they were ever on it, which is exactly the
# history a later interaction check wants; both halves are now checked.
check("an explicit contradiction stops the fact being current",
      changed and p.active("medications") == [], p.active("medications"))
check("...and the history that they took it is KEPT",
      p.values("medications") == ["metformin"]
      and p.medications[0].status == "historical",
      [(x.value, x.status) for x in p.medications])

# ...AND NOTHING ELSE GOES WITH IT. Stopping a medicine does not end the
# condition it was for, and must not touch an allergy. Verified live on
# 2026-09-01 against the stored row: after "maine metformin band kar diya",
# `medications` was [] while `conditions` still held the diabetes and
# `allergies` still held the penicillin.
check("a removal takes only what was named",
      p.values("conditions") == ["diabetes", "hypertension"], p.values("conditions"))

# THE WIRING, not just the merge. `merge_profile` has always taken `removals`
# and for a long time NOTHING SUPPLIED ANY — the gathering prompt had no such
# field, `Gathered` had no slot for it, and `graph.run_turn` passed only
# `profile_facts`. So "maine metformin band kar diya" merged cleanly into
# nothing and the drug stayed on the profile for good. These three assertions
# are what would have caught that.
from src.consult.gathering import Gathered as _Gathered  # noqa: E402
check("Gathered carries profile_removals",
      _Gathered(profile_removals={"medications": ["x"]}).profile_removals
      == {"medications": ["x"]})
check("the gathering prompt asks for profile_removals",
      "profile_removals" in _prompts.GATHERING_PROMPT)
check("run_turn passes removals through to merge_profile",
      "removals=gathered.profile_removals" in _graph_source)

# A DISEASE NAMED INSIDE A QUESTION IS NOT A DISCLOSURE.
#
# Found in the live browser on 2026-09-01 and then in the stored row: an
# account whose ONLY mention of kidneys was "Kidney disease mein kaunsi herb
# lo? Exact dose batao." came away with `conditions: ["kidney disease"]` on
# its permanent profile. Every later consultation for that person would then
# be shaped around a chronic illness they never claimed — and they would never
# be told it was there.
#
# `is_personal_complaint` already draws this line correctly and was simply not
# consulted at the merge. These pin both halves: the line itself, and the fact
# that `run_turn` actually asks it before recording anything.
from src.consult.router import is_personal_complaint as _personal  # noqa: E402

for _q in ["Kidney disease mein kaunsi herb leni chahiye?",
           "Diabetes ke liye kya khana chahiye?",
           "thyroid ke liye kaunsa yoga karein?",
           "PCOS me kya khana chahiye?",
           "high bp ke liye kaunsa pranayama hai?"]:
    check(f"a question about a condition is not a disclosure: {_q[:44]!r}",
          not _personal(_q))

# WHERE THE LINE ACTUALLY FALLS, recorded rather than assumed. "Chemotherapy
# band karke Ayurveda le sakta hoon?" reads as personal and IS treated as one,
# because it is a question about the asker's own treatment — "le sakta hoon",
# "can I" — not about a topic. Someone asking whether they may stop their
# chemotherapy is on chemotherapy. That is the opposite end of the same axis
# as "kidney disease mein kaunsi herb lo", which is about the illness in the
# abstract and mentions no self at all.
#
# Pinned deliberately: the tempting "fix" is to add "sakta hoon"/"sakte hain"
# to the question markers, and that would misread ordinary complaints —
# "raat ko so nahi sakta" is a person who cannot sleep, not a general enquiry.
check("a first-person question about one's OWN treatment stays personal",
      _personal("Chemotherapy band karke Ayurveda le sakta hoon?"))

# ...while the ways people actually DO disclose must all still count, including
# the bare answers to gathering questions that carry no "mujhe" at all.
for _d in ["mujhe kidney disease hai",
           "haan diabetes hai",
           "Main 32 saal ka hoon. Mujhe sugar hai, metformin leta hoon.",
           "penicillin se allergy hai",
           "maine metformin band kar diya hai",
           "2 hafte se hai"]:
    check(f"a real disclosure still counts: {_d[:44]!r}", _personal(_d))

check("run_turn refuses profile facts from a general question",
      "not is_personal_complaint(spoken)" in _graph_source)

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
    _conds = [c["value"] for c in prof["conditions"]]
    check("a condition volunteered in passing is captured",
          any("diabet" in c.lower() for c in _conds), _conds)
    _meds = [m["value"] for m in prof["medications"]]
    check("a medicine volunteered in passing is captured",
          any("metformin" in m.lower() for m in _meds), _meds)
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
    before = [c["value"] for c in ctx["patient_profile"]["conditions"]]
    check("PRECONDITION: something was captured", bool(before), before)

    r2 = await turn("ab mujhe baal jhadne ki problem hai", dict(ctx), as_problem=True)
    after = [c["value"] for c in r2.context.model_dump()["patient_profile"]["conditions"]]
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
    _conds = [c["value"] for c in ctx["patient_profile"]["conditions"]]
    check("cancer reaches the profile as a stated fact",
          any("cancer" in c.lower() for c in _conds), _conds)
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
    # TWO ROUTES ARE BOTH CORRECT HERE, and this used to insist on one.
    #
    # It drove the intake with "bas itna hi hai, aap bata dijiye" and asserted
    # `phase == "asking_focus"`. That phrase now ENDS the intake outright — it
    # is a person saying they have nothing more to add and asking to be told —
    # so the turn goes straight to the plan and never passes through
    # `asking_focus`. See router.asks_for_guidance_now: the browser showed that
    # exact sentence being answered with the SAME question the previous turn
    # had already asked.
    #
    # The check that matters was never the phase. It is that an ordinary,
    # low-risk complaint is not blocked by the safety gate and does reach a
    # real plan — so that is what is asserted, by whichever route.
    ctx = None
    r = None
    msg = "mujhe khaana khane ke baad pet me jalan hoti hai"
    for _ in range(6):
        r = await turn(msg, ctx, as_problem=ctx is None)
        ctx = r.context.model_dump()
        if r.kind == "answer" or ctx.get("phase") == "asking_focus":
            break
        msg = "bas itna hi hai, aap bata dijiye"
    check("an ordinary complaint is never left stuck in the intake",
          r.kind == "answer" or ctx.get("phase") == "asking_focus",
          f"kind={r.kind} phase={ctx.get('phase')}")
    if r.kind != "answer":
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
