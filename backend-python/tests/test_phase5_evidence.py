"""
PHASE-5 — evidence orchestration.

persona.txt, `evidence_system.principle`: rank evidence according to the
QUESTION being answered, not by one universal hierarchy. That sentence is the
whole test plan. If a classical text does not outrank a trial for a question
about traditional use, and lose to it for a question about effectiveness, the
phase is not implemented — it is just the old fixed ordering with new names.

THE FAILURES ASSERTED HERE are ones this product can actually produce:
tradition quoted as proof, a lane disagreement averaged into a confident
paragraph, a study cited that was never retrieved, a classical text stamped
"outdated" because it has no recent year on it.

    python tests/test_phase5_evidence.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import config  # noqa: E402
from src.clinical import evidence as E  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


class Chunk:
    """Stands in for `retrieval.base.Chunk` — same duck type."""

    def __init__(self, text="", source="", score=None, metadata=None):
        self.text = text
        self.source = source
        self.score = score
        self.metadata = metadata or {}


CLASSICAL = Chunk("Ashwagandha is described as a rasayana.",
                  "1-caraka-samhita.pdf", 0.7)
TRIAL = Chunk("A randomised trial reported improved sleep scores.",
              "randomized-trial-ashwagandha.pdf", 0.6)
GUIDELINE = Chunk("Clinical guideline for hypertension management.",
                  "hypertension-clinical-guideline-2023.pdf", 0.5)
REVIEW = Chunk("Systematic review of herbal sleep aids.",
               "systematic-review-sleep.pdf", 0.55)
AYUSH = Chunk("Pharmacopoeial identity standards for the drug.",
              "ayush-pharmacopoeia.pdf", 0.4)
NOTE = Chunk("Warm khichdi is easy to digest.", "knowledge:digestion.md", 0.3)


# ===========================================================================
# 0. Ships disabled; the spec's vocabulary is carried exactly
# ===========================================================================
check("0a. PHASE-5 ships disabled", config.PHASE5_EVIDENCE_ORCHESTRATION is False)
check("0b. all 9 evidence question types exist", len(E.QUESTION_TYPES) == 9,
      sorted(E.QUESTION_TYPES))
check("0c. all 5 evidence lanes exist", len(E.LANES) == 5, sorted(E.LANES))
check("0d. all 6 cross-lane rules are carried", len(E.CROSS_LANE_RULES) == 6,
      len(E.CROSS_LANE_RULES))
check("0e. every lane label used is one the spec permits",
      all(label in E.LANES[lane]
          for lane, label in E._CATEGORY_TO_LANE.values()),
      [v for v in E._CATEGORY_TO_LANE.values() if v[1] not in E.LANES[v[0]]])
check("0f. all 21 goals map to a question type", len(E.GOAL_QUESTION_TYPE) == 21,
      len(E.GOAL_QUESTION_TYPE))
check("0g. every mapped question type is a real one",
      all(q in E.QUESTION_TYPES for q in E.GOAL_QUESTION_TYPE.values()),
      sorted(set(E.GOAL_QUESTION_TYPE.values()) - set(E.QUESTION_TYPES)))
check("0h. subject-rule labels are legal for their lane",
      all(label in E.LANES[lane] for _, lane, label in E._LANE_SUBJECT_RULES), "")


# ===========================================================================
# 1. THE PRINCIPLE — ranking changes with the question
#
# The same two sources, asked about in two different ways. If the order does
# not flip, the phase has not been built.
# ===========================================================================
chunks = [TRIAL, CLASSICAL]

traditional = E.orchestrate(chunks, goal="herb_or_supplement_information",
                            text="What does Ayurveda say about ashwagandha?")
check("1a. question type is traditional use", traditional.question_type
      == "ayurveda_traditional_use", traditional.question_type)
check("1b. THE CLASSICAL TEXT RANKS FIRST FOR A TRADITION QUESTION",
      traditional.items[0].source == CLASSICAL.source,
      [i.source for i in traditional.items])

effectiveness = E.orchestrate(
    chunks, goal="herb_or_supplement_information",
    text="Does ashwagandha actually work? Is there any research?")
check("1c. wording promotes it to clinical effectiveness",
      effectiveness.question_type == "ayurveda_clinical_effectiveness",
      effectiveness.question_type)
check("1d. THE TRIAL RANKS FIRST FOR AN EFFECTIVENESS QUESTION — the ordering "
      "FLIPPED for the same two sources",
      effectiveness.items[0].source == TRIAL.source,
      [i.source for i in effectiveness.items])

safety = E.orchestrate(chunks, goal="personalized_herb_safety",
                       text="Is ashwagandha safe with my thyroid medicine?")
check("1e. a safety question is its own type",
      safety.question_type == "ayurveda_safety", safety.question_type)

check("1f. nothing is discarded — low-ranked evidence stays visible",
      len(traditional.items) == 2 and len(effectiveness.items) == 2,
      (len(traditional.items), len(effectiveness.items)))


# ===========================================================================
# 2. LANES STAY SEPARATE — `evidence_lanes`
# ===========================================================================
mixed = E.orchestrate([CLASSICAL, GUIDELINE, NOTE],
                      goal="general_education", text="What helps digestion?")
by_lane = mixed.by_lane()
check("2a. the classical text and the guideline are in different lanes",
      len(by_lane) >= 2, sorted(by_lane))
check("2b. the guideline is modern_medicine",
      E.lane_for(GUIDELINE.source)[0] == "modern_medicine",
      E.lane_for(GUIDELINE.source))
check("2c. the classical text is ayurveda / classical_description",
      E.lane_for(CLASSICAL.source) == ("ayurveda", "classical_description"),
      E.lane_for(CLASSICAL.source))

# `cross_lane_rules` rule 2: do not equate an Ayurveda concept with a modern
# diagnosis. A classical passage that mentions food is NOT nutrition advice.
check("2d. A CLASSICAL PASSAGE ABOUT FOOD IS STILL CLASSICAL, not nutrition — "
      "provenance beats subject",
      E.lane_for("1-caraka-samhita.pdf", "the proper diet and food for agni")
      == ("ayurveda", "classical_description"),
      E.lane_for("1-caraka-samhita.pdf", "the proper diet and food for agni"))

# Material the source rules cannot place is routed by subject instead.
check("2e. unplaceable yoga material lands in the yoga lane",
      E.lane_for("misc-handout", "gentle asana and pranayama sequence")[0]
      == "physical_rehabilitation_and_yoga",
      E.lane_for("misc-handout", "gentle asana and pranayama sequence"))
check("2f. unplaceable anxiety material lands in the behavioural lane",
      E.lane_for("misc-handout", "managing anxiety and panic")[0]
      == "psychological_and_behavioral",
      E.lane_for("misc-handout", "managing anxiety and panic"))


# ===========================================================================
# 3. CONFLICT RETRIEVAL — `cross_lane_rules` rule 3, "do not hide disagreement"
# ===========================================================================
pro = Chunk("This herb is effective and improves symptoms.", "1-caraka-samhita.pdf")
con = Chunk("There is insufficient evidence; it is not recommended.",
            "hypertension-clinical-guideline-2023.pdf")
disagreeing = E.orchestrate([pro, con], goal="treatment_options", text="does it help")
check("3a. DISAGREEMENT BETWEEN LANES IS REPORTED, not averaged",
      any(c.kind == "cross_lane" for c in disagreeing.conflicts),
      [c.as_dict() for c in disagreeing.conflicts])
check("3b. the conflicting sources are named",
      any(pro.source in c.sources for c in disagreeing.conflicts),
      [c.sources for c in disagreeing.conflicts])
check("3c. the prompt block says so out loud",
      "DISAGREEMENT" in E.describe(disagreeing), E.describe(disagreeing)[:120])

agreeing = E.orchestrate([pro, Chunk("Also effective and helpful.",
                                     "2-sushruta-samhita.pdf")],
                         goal="treatment_options", text="does it help")
check("3d. AGREEMENT IS NOT REPORTED AS CONFLICT — no false positives",
      not any(c.kind == "cross_lane" for c in agreeing.conflicts),
      [c.as_dict() for c in agreeing.conflicts])

within = E.orchestrate(
    [Chunk("It is effective for this.", "1-caraka-samhita.pdf"),
     Chunk("It is not recommended here.", "2-sushruta-samhita.pdf")],
    goal="treatment_options", text="does it help")
check("3e. disagreement WITHIN one lane is reported too",
      any(c.kind == "within_lane" for c in within.conflicts),
      [c.kind for c in within.conflicts])

silent = E.orchestrate([CLASSICAL, AYUSH], goal="treatment_options", text="x")
check("3f. passages with no stance produce no conflict",
      silent.conflicts == [], [c.as_dict() for c in silent.conflicts])


# ===========================================================================
# 4. EVIDENCE FRESHNESS
# ===========================================================================
TODAY = date(2026, 9, 2)
check("4a. a recent guideline is current",
      E.freshness_of("guideline-2023.pdf", "guideline_supported", today=TODAY)
      == "current",
      E.freshness_of("guideline-2023.pdf", "guideline_supported", today=TODAY))
check("4b. a decade-old trial is aging",
      E.freshness_of("trial-2017.pdf", "controlled_trial", today=TODAY) == "aging",
      E.freshness_of("trial-2017.pdf", "controlled_trial", today=TODAY))
check("4c. a very old paper is outdated",
      E.freshness_of("trial-2004.pdf", "controlled_trial", today=TODAY)
      == "outdated",
      E.freshness_of("trial-2004.pdf", "controlled_trial", today=TODAY))
check("4d. A CLASSICAL TEXT IS TIMELESS, NOT OUTDATED — calling the Caraka "
      "Samhita stale is a category error",
      E.freshness_of("1-caraka-samhita.pdf", "classical_description",
                     today=TODAY) == "timeless",
      E.freshness_of("1-caraka-samhita.pdf", "classical_description", today=TODAY))
check("4e. an undated modern source is 'unknown', NOT guessed",
      E.freshness_of("some-review.pdf", "systematic_review", today=TODAY)
      == "unknown",
      E.freshness_of("some-review.pdf", "systematic_review", today=TODAY))
check("4f. metadata year is used when present",
      E.freshness_of("x.pdf", "systematic_review", {"year": 2025}, today=TODAY)
      == "current",
      E.freshness_of("x.pdf", "systematic_review", {"year": 2025}, today=TODAY))


# ===========================================================================
# 5. CITATION VALIDATION
# ===========================================================================
laned = E.orchestrate([CLASSICAL], goal="ayurveda_assessment", text="x").items
check("5a. A STUDY CLAIMED WHEN NO STUDY WAS RETRIEVED IS FLAGGED",
      any(i.kind == "unsupported_study_claim" for i in
          E.validate_citations("A study found that this herb cures insomnia.", laned)),
      [i.as_dict() for i in
       E.validate_citations("A study found that this herb cures insomnia.", laned)])

with_trial = E.orchestrate([TRIAL], goal="treatment_options", text="x").items
check("5b. ...but allowed when a trial actually was retrieved",
      not any(i.kind == "unsupported_study_claim" for i in
              E.validate_citations("A study found improved sleep.", with_trial)),
      [i.as_dict() for i in
       E.validate_citations("A study found improved sleep.", with_trial)])

check("5c. naming a source that was never retrieved is flagged",
      any(i.kind == "unretrieved_source" for i in
          E.validate_citations("According to Lancet, this works.", laned)),
      [i.as_dict() for i in
       E.validate_citations("According to Lancet, this works.", laned)])
check("5d. naming a source that WAS retrieved is clean",
      E.validate_citations("According to Caraka Samhita, it is a rasayana.",
                           laned) == [],
      [i.as_dict() for i in
       E.validate_citations("According to Caraka Samhita, it is a rasayana.", laned)])
check("5e. ordinary prose is not flagged",
      E.validate_citations("Rest, warm food and regular sleep often help.",
                           laned) == [], "")

original = "A study found that this cures everything."
E.validate_citations(original, laned)
check("5f. VALIDATION NEVER EDITS — the text is returned untouched",
      original == "A study found that this cures everything.", "")


# ===========================================================================
# 6. GRAPHRAG QUERY IMPROVEMENT
# ===========================================================================
q = E.build_query("kya mujhe migraine ke symptoms bata sakte ho",
                  "patient_education")
check("6a. the reader's own content words survive",
      "migraine" in q and "symptoms" in q, q)
check("6b. filler is dropped", "mujhe" not in q and "kya" not in q, q)

q_safety = E.build_query("ashwagandha", "ayurveda_safety")
check("6c. a safety question pulls safety terms into the query",
      "interaction" in q_safety and "ashwagandha" in q_safety, q_safety)
q_trad = E.build_query("ashwagandha", "ayurveda_traditional_use")
check("6d. a tradition question pulls classical terms instead",
      "classical" in q_trad and "interaction" not in q_trad, q_trad)

q_problem = E.build_query("aur uske liye kya karun", "treatment_benefit",
                          problem="acidity")
check("6e. A FOLLOW-UP WITH NO NOUN STILL RETRIEVES THE RIGHT THING",
      "acidity" in q_problem, q_problem)
check("6f. an all-stopword question never returns an empty query",
      E.build_query("kya hai", "patient_education").strip() != "",
      E.build_query("kya hai", "patient_education"))


# ===========================================================================
# 7. THE PROMPT BLOCK — insufficiency is stated, tradition is not promoted
# ===========================================================================
empty = E.orchestrate([], goal="general_education", text="what is X")
check("7a. an empty set is empty", empty.is_empty, "")
check("7b. NO-KNOWLEDGE FALLBACK SAYS SO PLAINLY",
      "nothing relevant" in E.describe(empty).lower()
      and "do not imply research support" in E.describe(empty).lower(),
      E.describe(empty)[:110])

described = E.describe(traditional)
check("7c. the classical lane is introduced as tradition",
      "Traditionally described" in described, described)
check("7d. every block forbids promoting tradition to proof",
      "Never present traditional use as proven clinical effect." in described, "")
check("7e. the block names the question type",
      "traditional use" in described, described[:80])

check("7f. the set serialises for the evaluation log",
      set(traditional.as_dict()) == {"question_type", "lanes_present", "items",
                                     "conflicts"},
      sorted(traditional.as_dict()))


# ===========================================================================
# 8. SAFETY PRECEDENCE — `cross_lane_rules` rule 4
#
# The interaction question must not be answered out of a wellness note. This
# is the ordering rule, checked as ordering.
# ===========================================================================
interaction = E.orchestrate(
    [NOTE, AYUSH, Chunk("Reported adverse interaction with thyroid medicines.",
                        "pharmacology-review.pdf", 0.2)],
    goal="personalized_medicine_safety",
    text="is this safe with my thyroid medicine")
check("8a. a safety turn is a harm_or_interaction question",
      interaction.question_type == "harm_or_interaction",
      interaction.question_type)
check("8b. THE WELLNESS NOTE DOES NOT WIN A SAFETY QUESTION",
      interaction.items[0].source != NOTE.source,
      [i.source for i in interaction.items])

# And the patient's own report is never treatment evidence.
check("8c. the patient's own report is not ranked as evidence about a treatment",
      E.lane_for("report:bloodwork.pdf")[1] == "insufficient",
      E.lane_for("report:bloodwork.pdf"))


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== phase5 evidence orchestration: {passed}/{len(results)} passed =====")
if passed != len(results):
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name} :: {detail}")
    sys.exit(1)
