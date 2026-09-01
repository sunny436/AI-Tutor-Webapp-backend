"""
P0-1: longitudinal patient state (facts with provenance) and episodes.

Wholly DETERMINISTIC — no model, no network. These are the rules that decide
whether a person's allergy survives and whether a stopped drug is still
treated as current, and they must behave the same on the day the LLM is
rate-limited, wrong or unreachable. Same reason `test_safety.py` is a unit
suite.

    python tests/test_clinical_state.py
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

from src.clinical import episodes as ep  # noqa: E402
from src.consult.schema import ConsultContext, Episode, Fact, PatientProfile  # noqa: E402
from src.consult.state import (  # noqa: E402
    merge_profile,
    render_profile,
    user_fragments,
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# ===========================================================================
# 1. A fact carries where it came from and when it was last true.
# ===========================================================================
f = Fact(value="  metformin  ")
check("a fact trims its value", f.value == "metformin", f.value)
check("a fact defaults to patient-stated and active",
      f.source == "patient" and f.status == "active" and f.confidence == 1.0)

# READING A PROFILE WRITTEN BEFORE FACTS EXISTED. Convex stores the profile as
# a JSON string, so every row already out there is flat lists of strings. If
# this ever stops working, every returning patient silently becomes a stranger.
v1 = PatientProfile.model_validate(
    {"age": "32", "conditions": ["diabetes"], "medications": ["metformin"],
     "allergies": ["penicillin"]}
)
check("a v1 flat profile still loads",
      v1.values("conditions") == ["diabetes"]
      and v1.values("medications") == ["metformin"], v1.values("conditions"))
check("v1 values become active patient-stated facts",
      all(x.status == "active" and x.source == "patient" for x in v1.medications))
check("a v2 profile round-trips through JSON",
      PatientProfile.model_validate(v1.model_dump()).values("allergies") == ["penicillin"])


# ===========================================================================
# 2. merge_profile — the rules that decide what a person is
# ===========================================================================
p = PatientProfile()
p, changed = merge_profile(p, {"age": "29", "conditions": ["diabetes"],
                               "medications": ["metformin"]})
check("new facts are added", changed and p.age == "29"
      and p.values("conditions") == ["diabetes"])

p, changed = merge_profile(p, {"age": "30"})
check("a corrected scalar REPLACES the old value", changed and p.age == "30", p.age)

p, changed = merge_profile(p, {"conditions": ["hypertension"]})
check("a list merges rather than replacing",
      p.values("conditions") == ["diabetes", "hypertension"], p.values("conditions"))

p, changed = merge_profile(p, {"conditions": ["DIABETES"]})
check("a case-different duplicate is not re-added",
      p.values("conditions") == ["diabetes", "hypertension"], p.values("conditions"))
check("...but saying it again RE-CONFIRMS it",
      p.conditions[0].last_confirmed_at != "", p.conditions[0].last_confirmed_at)

p, changed = merge_profile(p, {"allergies": []})
check("SILENCE IS NOT RETRACTION — unmentioned facts survive",
      not changed and p.values("conditions") == ["diabetes", "hypertension"])

# THE MODEL'S OWN INTERPRETATION IS REFUSED AT THE WRITE POINT.
# PatientProfile's docstring has always said "user-stated facts only"; with a
# `source` on every fact that rule is now checkable rather than merely stated.
p, changed = merge_profile(p, {"conditions": [{"value": "pitta imbalance",
                                               "source": "inferred"}]})
check("an INFERRED fact is never written to the profile",
      not changed and "pitta imbalance" not in p.values("conditions"),
      p.values("conditions"))

# --- retraction ------------------------------------------------------------
p, changed = merge_profile(p, {}, removals={"medications": ["metformin"]})
check("an explicit contradiction changes status, it does not delete",
      changed and p.values("medications") == ["metformin"]
      and p.medications[0].status == "historical",
      [(x.value, x.status) for x in p.medications])
check("a stopped medicine is NOT active",
      p.active("medications") == [], p.active("medications"))
check("a removal takes only what was named",
      p.values("conditions") == ["diabetes", "hypertension"], p.values("conditions"))

# Retracting twice is not a change the second time — otherwise every turn
# after a stop would write to Convex again for nothing.
_p2, changed_again = merge_profile(p, {}, removals={"medications": ["metformin"]})
check("retracting an already-stopped fact reports no change", not changed_again)

# ...and restarting it is a real change back to active.
p, changed = merge_profile(p, {"medications": [{"value": "metformin",
                                                "status": "active"}]})
check("restarting a stopped medicine makes it active again",
      changed and p.active("medications") == ["metformin"],
      [(x.value, x.status) for x in p.medications])


# ===========================================================================
# 3. What the prompt and the safety scan see
# ===========================================================================
q = PatientProfile()
q, _ = merge_profile(q, {"conditions": ["diabetes"], "medications": ["metformin"]})
q, _ = merge_profile(q, {}, removals={"medications": ["metformin"]})
rendered = render_profile(q)
check("render_profile marks a stopped medicine as stopped",
      "metformin (in the past, stopped)" in rendered, rendered)
check("render_profile leaves an active fact unmarked",
      "diabetes" in rendered and "diabetes (" not in rendered, rendered)
check("render_profile still emits human labels, never field identifiers",
      not any(t in rendered for t in ("patient_profile", "family_history", "_")),
      rendered)

# A RESOLVED SERIOUS CONDITION MUST NOT KEEP FIRING THE DEEP-DIVE.
#
# `user_fragments`, not `safety_fragments`: the first is what
# `safety.is_serious_condition` reads (only what the PATIENT said, because the
# assistant names conditions routinely when explaining when to see a doctor);
# the second is the emergency keyword scan over the whole transcript and does
# not read the profile at all. The deep-dive is driven by the former.
r = PatientProfile()
r, _ = merge_profile(r, {"conditions": ["cancer"]})
ctx = ConsultContext(patient_profile=r)
check("an ACTIVE serious condition still reaches the serious-condition scan",
      any("cancer" in f for f in user_fragments(ctx)), user_fragments(ctx))
r.conditions[0].status = "resolved"
ctx = ConsultContext(patient_profile=r)
check("a RESOLVED condition no longer reaches it",
      not any("cancer" in f for f in user_fragments(ctx)),
      [f for f in user_fragments(ctx) if "cancer" in f])


# ===========================================================================
# 4. Episodes — one health concern each, across every conversation
# ===========================================================================
eps: list[Episode] = []
eps, acidity, new = ep.select(eps, "mujhe acidity ho rahi hai", "Acidity")
check("the first complaint opens an episode", new and acidity.status == "active")

eps, knee, new = ep.select(eps, "mere ghutne me dard hai", "Knee pain")
check("a different complaint opens a SECOND episode",
      new and knee.episode_id != acidity.episode_id and len(eps) == 2)

eps, again, new = ep.select(eps, "acidity phir se ho rahi hai", "Acidity")
check("the same complaint returns to its own episode",
      not new and again.episode_id == acidity.episode_id and len(eps) == 2)

# THE SPLIT THAT MATTERS. "pain" is a stop word precisely so that these two do
# not collapse into one episode — a knee and a chest are not the same problem.
eps, chest, new = ep.select(eps, "seene me dard ho raha hai", "Chest pain")
check("knee pain and chest pain stay separate episodes",
      new and chest.episode_id != knee.episode_id, [e.problem_name for e in eps])

# ...and the merge that matters: a recurrence must find its own history.
acidity.status = "resolved"
eps, back, new = ep.select(eps, "acidity wapas aa gayi", "Acidity")
check("a recurrence reopens the SAME episode, with its history",
      not new and back.episode_id == acidity.episode_id, [e.problem_name for e in eps])
check("...and is counted as a recurrence, not a first occurrence",
      back.status == "active" and back.recurrences == 1,
      f"status={back.status} recurrences={back.recurrences}")
check("a recurrence does not duplicate the episode", len(eps) == 3, len(eps))

check("several episodes stay open at once",
      sum(1 for e in eps if e.status == "active") == 3,
      [(e.problem_name, e.status) for e in eps])

# What a prompt is told about the OTHER problems — terse, and never the
# current one, so the assistant knows they exist without reciting a case file.
line = ep.render(eps, back.episode_id)
check("render names the other open problems", "Knee pain" in line and "Chest pain" in line, line)
check("render never names the CURRENT problem", "Acidity" not in line, line)
check("render is empty when nothing else is open", ep.render([back], back.episode_id) == "")

# Bounded, like every other list that rides on the context.
many = []
for i in range(ep.MAX_EPISODES + 5):
    many, _e, _n = ep.select(many, f"problem{i} symptom{i}", f"Condition{i}")
check("episodes are bounded", len(many) <= ep.MAX_EPISODES, len(many))
check("the episode in hand survives the bound",
      any(e.problem_name == f"Condition{ep.MAX_EPISODES + 4}" for e in many))

# An episode carries the answers that stop a question being asked twice.
back.negative_findings.append("no blood in stool")
back.red_flags_checked.append("bleeding")
check("an episode records what was asked and answered",
      "no blood in stool" in back.negative_findings
      and "bleeding" in back.red_flags_checked)

# Episodes survive the JSON round trip the client performs every turn.
ctx = ConsultContext(episodes=eps, active_episode_id=back.episode_id)
restored = ConsultContext.model_validate(ctx.model_dump())
check("episodes survive the context round trip",
      len(restored.episodes) == 3
      and restored.active_episode_id == back.episode_id
      and ep.get(restored.episodes, back.episode_id) is not None)


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== clinical state: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}{f' [{detail}]' if detail else ''}")
sys.exit(0 if passed == len(results) else 1)
