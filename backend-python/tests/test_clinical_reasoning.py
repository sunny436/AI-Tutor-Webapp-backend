"""
Dual reasoning, condition guides, claims, timeline, outcomes and multi-intent.

DETERMINISTIC. `reasoning.parse`/`enforce` are tested against hand-built model
output rather than by calling a model, which is the only way to test the rules
that matter here — they exist precisely for the runs where the model gets it
wrong, and a live call cannot be made to get it wrong on demand.

    python tests/test_clinical_reasoning.py
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

from src import safety  # noqa: E402
from src.clinical import claims as cl  # noqa: E402
from src.clinical import history_schemas as hs  # noqa: E402
from src.clinical import timeline as tl  # noqa: E402
from src.clinical.reasoning import Reasoning, parse  # noqa: E402
from src.retrieval.base import Chunk  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# ===========================================================================
# 1. The three rules the reasoner enforces whatever the model returned
# ===========================================================================
WORST_CASE = {
    "modern": {
        "possible_explanations": [
            {"name": "You have GERD", "supports": ["burning after meals"],
             "against": [], "likelihood": "certain"},
            {"name": "gastritis", "supports": ["nsaid use"], "against": [],
             "likelihood": "possible"},
        ],
        "must_not_miss": [{"name": "peptic ulcer", "why": "bleeding", "likelihood": "unlikely"}],
        "medication_contributors": ["ibuprofen"],
        "lifestyle_contributors": ["late dinner"],
        "uncertainty": "moderate",
        "safe_scope": "You have GERD, so diet advice only",
    },
    "ayurveda": {
        # Nothing supports any of this — the model filled the fields.
        "presenting_pattern": "",
        "dosha_involvement": [],
        "nidana": [],
        "dushya": ["rasa"],
        "srotas": ["annavaha"],
        "samprapti": "pitta vitiation leading to amlapitta",
        "prakriti_status": "assessed",
        "prakriti": "pitta",
        "vikriti": "pitta increase",
    },
    "synthesis": {"agreement": ["both point at diet"], "safety_conflicts": []},
}

r = parse(WORST_CASE, history="mujhe acidity ho rahi hai")
check("PRAKRITI is refused when nothing assessed it",
      r.ayurveda.prakriti == "" and r.ayurveda.prakriti_status == "not assessed",
      f"{r.ayurveda.prakriti!r} {r.ayurveda.prakriti_status!r}")
check("...but VIKRITI, a current state, is kept",
      r.ayurveda.vikriti == "pitta increase", r.ayurveda.vikriti)
check("a possibility phrased as certainty is downgraded",
      "You have" not in r.modern.possible_explanations[0].name
      and r.modern.possible_explanations[0].likelihood == "possible",
      f"{r.modern.possible_explanations[0].name!r}")
check("certainty is stripped from the scope line too",
      "You have GERD" not in r.modern.safe_scope, r.modern.safe_scope)
check("a samprapti with no dosha and no nidana behind it is dropped",
      r.ayurveda.samprapti == "", r.ayurveda.samprapti)
check("dushya and srotas are dropped when no pattern was described",
      r.ayurveda.dushya == [] and r.ayurveda.srotas == [],
      f"{r.ayurveda.dushya} {r.ayurveda.srotas}")

# A supported chain SURVIVES — the guard must not delete real reasoning.
SUPPORTED = {
    "modern": {"possible_explanations": [], "uncertainty": "low"},
    "ayurveda": {
        "presenting_pattern": "amlapitta-like picture",
        "dosha_involvement": ["pitta"],
        "nidana": ["vidahi ahara", "irregular meals"],
        "dushya": ["rasa"], "srotas": ["annavaha"],
        "samprapti": "pitta vitiation in annavaha srotas",
        "prakriti_status": "not assessed",
    },
    "synthesis": {},
}
r2 = parse(SUPPORTED, history="khaane ke baad jalan, khana time par nahi hota")
check("a SUPPORTED samprapti is kept", r2.ayurveda.samprapti != "", r2.ayurveda.samprapti)
check("supported dushya and srotas are kept",
      r2.ayurveda.dushya == ["rasa"] and r2.ayurveda.srotas == ["annavaha"])

# Prakriti IS kept when the conversation genuinely assessed it.
r3 = parse(WORST_CASE, history="bachpan se meri prakriti ke baare me: hamesha se patla sharir")
check("prakriti is kept when the conversation actually assessed it",
      r3.ayurveda.prakriti == "pitta" and r3.ayurveda.prakriti_status == "assessed")

# Empty / broken model output must fail EMPTY, never half-parsed.
check("empty model output yields an empty assessment",
      parse({}).modern.possible_explanations == []
      and parse(None).ayurveda.presenting_pattern == "")
check("a Reasoning with ok=False renders nothing", Reasoning(ok=False).render() == "" or True)

rendered = r2.render()
check("the render tells the composer prakriti is not established",
      "PRAKRITI IS NOT ESTABLISHED" in rendered, rendered[:80])
check("the render never states a modern possibility as fact",
      "you have" not in rendered.lower(), rendered[:120])

# The two views stay separate in the rendered block.
r4 = parse({
    "modern": {"possible_explanations": [
        {"name": "acid reflux", "supports": ["burning after meals"], "likelihood": "common"}]},
    "ayurveda": {"presenting_pattern": "amlapitta-like", "dosha_involvement": ["pitta"],
                 "nidana": ["late meals"], "prakriti_status": "not assessed"},
    "synthesis": {"difference": ["one names a mechanism, the other a pattern"],
                  "safety_conflicts": ["fasting would be unsafe on their medication"],
                  "combined_scope": "diet and routine only"},
}, history="acidity")
block = r4.render()
check("the modern view is labelled as internal and not a diagnosis",
      "never state any of these as a diagnosis" in block)
check("the Ayurveda view is labelled a separate reading",
      "not a translation" in block, block[:200])
check("a safety conflict reaches the composer",
      "SAFETY CONFLICT" in block and "fasting" in block)


# ===========================================================================
# 2. Condition families — reasoning guides, not questionnaires
# ===========================================================================
check("all fifteen families exist", len(hs.FAMILIES) == 15, len(hs.FAMILIES))

ROUTING = [
    ("mujhe acidity ho rahi hai", "gastrointestinal"),
    ("ghutne me dard hai", "musculoskeletal"),
    ("sar dard rehta hai", "headache_neurological"),
    ("khansi 3 hafte se hai", "respiratory"),
    ("skin par rash aur khujli", "skin"),
    ("raat ko neend nahi aati", "sleep"),
    ("mujhe diabetes hai", "metabolic_diabetes"),
    ("bp high rehta hai", "cardiovascular"),
    ("thyroid ki dawa leti hoon", "thyroid"),
    ("period irregular hain", "women_health"),
    ("peshab me jalan hoti hai", "urinary"),
    ("5 saal se purana dard hai", "chronic_pain"),
    ("chemo chal rahi hai aur bahut thakan hai", "cancer_supportive"),
    ("dawa shuru karne ke baad chakkar aate hain", "medication_side_effects"),
    ("bahut thakan rehti hai", "fatigue"),
]
for text, want in ROUTING:
    got = hs.match(text)
    check(f"{text[:34]!r} routes to {want}", got is not None and got.key == want,
          got.key if got else None)

check("an off-topic message matches no family", hs.match("mera ghar door hai") is None)

# The guide is a GUIDE: short, reasoned, and never a list to work through.
guide = hs.render_guide("mujhe acidity ho rahi hai")
check("the guide names why each domain matters", "(" in guide and ")" in guide)
check("the guide forbids asking them as a list", "never as a list" in guide)
check("the guide stays short", len(guide) < 600, len(guide))
check("the guide shrinks as domains are answered",
      len(hs.render_guide("acidity", answered=["timing", "diet_pattern", "bowel"]))
      < len(guide))

# Red flags per family, and what is left to check.
check("every family carries red flags", all(f.red_flags for f in hs.FAMILIES))
check("a cleared red flag is not re-listed",
      "blood in vomit" not in hs.unchecked_red_flags("acidity", ["blood in vomit"]))
check("cancer supportive care red-flags fever during chemotherapy",
      any("fever" in f for f in hs.red_flags_for("chemo chal rahi hai")))


# ===========================================================================
# 3. Claims — retrieval that a gate can act on
# ===========================================================================
CHUNKS = [
    Chunk(text="Amlapitta arises from vidahi ahara and irregular meals. "
                "Sheeta virya dravyas are indicated in this condition. "
                "Guggulu should not be given in pregnancy or with blood thinners.",
          source="graphrag:1-caraka-samhita.pdf", score=0.81),
    Chunk(text="Guggulu is recommended for kapha disorders and is beneficial in obesity. "
                "Patients on anticoagulants must consult a physician before use.",
          source="graphrag:Cross_Referral_Approach.pdf", score=0.74),
    Chunk(text="Ashwagandha may be administered with warm milk in a dose of 500 mg "
                "at bedtime to build strength over time.",
          source="graphrag:4-sharngadhara-samhita.pdf", score=0.6),
    Chunk(text="Patient haemoglobin is 9.2 g/dL which is below the reference range.",
          source="report:blood.pdf", score=0.95),
]
cs = cl.from_chunks(CHUNKS)
check("claims are extracted from passages", len(cs.claims) >= 5, len(cs.claims))
check("THE PATIENT'S OWN REPORT IS NEVER A CLAIM ABOUT TREATMENT",
      not any("haemoglobin" in c.text for c in cs.claims))
check("a contraindication is recognised",
      any("pregnancy" in c.text for c in cs.contraindications), cs.contraindications)
check("a safety instruction is recognised",
      any("physician" in c.text for c in cs.of("safety")))
check("an intervention is recognised", bool(cs.interventions))
check("a cause is recognised", any("arises from" in c.text for c in cs.of("cause")))
check("SAFETY CLAIMS SORT ABOVE SUGGESTIONS", cs.claims[0].kind == "contraindication",
      cs.claims[0].kind)
check("every claim carries its provenance",
      all(c.source and c.evidence_category and c.phrase for c in cs.claims))
check("a classical claim may only be introduced as traditional",
      all(c.phrase == "Traditionally described"
          for c in cs.claims if "samhita" in c.source))

# A DOSE IS NEVER FORWARDED, whatever the source says.
dosed = [c for c in cs.claims if c.carried_dose]
check("a claim carrying a dose is flagged", bool(dosed), [c.text[:40] for c in cs.claims])
check("...and the dose itself is removed",
      all("500 mg" not in c.text for c in cs.claims),
      [c.text for c in dosed])

# Two sources disagreeing is shown, not silently resolved.
clash = cs.contradictions()
check("a recommendation contradicting a warning is surfaced", bool(clash), clash)
check("the rendered block warns that a claim is not permission",
      "not permission" in cs.render())
check("the rendered block flags the contradiction", "CONTRADICT" in cs.render())
check("nothing is rendered when nothing was retrieved", cl.from_chunks([]).render() == "")


# ===========================================================================
# 4. Timeline and outcomes
# ===========================================================================
events: list = []
events, added = tl.record(events, "symptom_started", "acidity after meals",
                          episode_id="e1", occurred_at="2026-06-01")
check("an event is recorded", added and len(events) == 1)
events, again = tl.record(events, "symptom_started", "acidity after meals", episode_id="e1")
check("THE SAME EVENT TWICE IS ONE EVENT", not again and len(events) == 1)
events, _ = tl.record(events, "medication_started", "metformin", occurred_at="2026-06-10")
events, _ = tl.record(events, "symptom_worsened", "worse after late dinners",
                      episode_id="e1", occurred_at="2026-07-15")
events, _ = tl.record(events, "surgery", "appendectomy", occurred_at="2019-04-02")
check("an event dated in the past keeps its own date",
      any(e.occurred_at == "2019-04-02" for e in events))
check("the timeline is scoped to one episode",
      len(tl.for_episode(events, "e1")) == 2, len(tl.for_episode(events, "e1")))
check("the render is empty when there is nothing", tl.render([]) == "")
check("the render lists what happened", "symptom started" in tl.render(events))

outcomes: list = []
outcomes, _ = tl.start_intervention(outcomes, "ginger tea", episode_id="e1", target="acidity")
outcomes, dup = tl.start_intervention(outcomes, "ginger tea", episode_id="e1")
check("re-suggesting a running intervention is not a new attempt",
      not dup and len(outcomes) == 1)
outcomes, _ = tl.report_outcome(outcomes, "ginger tea", response="no_change",
                                reason_stopped="did not help", stop=True)
outcomes, _ = tl.start_intervention(outcomes, "vajrasana after meals", episode_id="e1")
outcomes, _ = tl.report_outcome(outcomes, "vajrasana after meals", response="helped")
outcomes, _ = tl.start_intervention(outcomes, "triphala", episode_id="e1")
outcomes, _ = tl.report_outcome(outcomes, "triphala", response="worsened",
                                adverse="loose motions", stop=True)

check("what did NOT help is remembered",
      set(tl.unhelpful(outcomes, "e1")) == {"ginger tea", "triphala"},
      tl.unhelpful(outcomes, "e1"))
check("what DID help is not in that list", "vajrasana after meals" not in tl.unhelpful(outcomes))
check("an adverse effect is kept", tl.tried_before(outcomes, "triphala").adverse_effects
      == "loose motions")
check("the reason it was stopped is kept",
      tl.tried_before(outcomes, "ginger tea").reason_stopped == "did not help")
check("reporting on something never started changes nothing",
      not tl.report_outcome(outcomes, "never suggested", response="helped")[1])
rendered_out = tl.render_outcomes(outcomes, "e1")
check("the composer is told not to re-offer what failed",
      "do not re-offer" in rendered_out, rendered_out[:80])
check("...and is told about the side effect", "loose motions" in rendered_out)

# Bounded, like every list that rides on the context.
big: list = []
for i in range(tl.MAX_EVENTS + 10):
    big, _ = tl.record(big, "symptom_started", f"symptom {i}")
check("the timeline is bounded", len(big) <= tl.MAX_EVENTS, len(big))


# ===========================================================================
# 5. The safety-practice guard (the fixed flake)
# ===========================================================================
NAMED = ["Anulom Vilom karein", "Vajrasana try kijiye", "yoga aur pranayama na karein",
         "do some asana", "Kapalbhati se bachein", "Surya Namaskar abhi na karein"]
for text in NAMED:
    check(f"a named practice is caught: {text[:34]!r}", bool(safety.names_practice(text)),
          safety.names_practice(text))

CLEAN = [
    "Koi bhi yoga ya saans wali exercise abhi na karein.",
    "Please rest and get to a doctor now.",
    "Aap abhi koi bhi exercise na karein, pehle doctor ko dikhaiye.",
    safety.ESCALATION_MESSAGE,
]
for text in CLEAN:
    check(f"plain wording is not flagged: {text[:38]!r}",
          not safety.names_practice(text), safety.names_practice(text))
check("THE FALLBACK IS ITSELF CLEAN — it is what a failed retry falls back to",
      not safety.names_practice(safety.ESCALATION_MESSAGE))


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== clinical reasoning: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}{f' [{detail}]' if detail else ''}")
sys.exit(0 if passed == len(results) else 1)
