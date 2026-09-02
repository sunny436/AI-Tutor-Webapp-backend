"""
clinical/evidence.py
--------------------
PHASE-5 — evidence orchestration.

persona.txt, `evidence_system.principle`:

    "Rank evidence according to the question being answered rather than using
     one simplistic universal hierarchy."

THE FAILURE THIS PREVENTS. `evidence_class.py` already answers "how strong is
this source?" with ONE fixed ordering — a guideline outranks a classical text,
always. That ordering is right for "does ashwagandha work?" and wrong for
"what does Ayurveda traditionally say about ashwagandha?", where the classical
text IS the best available evidence and the guideline is off-topic. A single
hierarchy makes the product answer the second question with material that does
not address it, and then rank the material that does address it last.

So the ranking here is a function of the QUESTION, not of the source alone.
`evidence_class` stays the authority on what a source is and how it may be
introduced; this module decides which of those sources matters for the turn in
front of us, keeps the lanes apart, and reports where they disagree.

WHAT THIS MODULE DOES NOT DO. It does not rewrite text, does not compose an
answer, and does not decide safety — `safety.py` and `triage.py` keep that,
and `cross_lane_rules` explicitly subordinates everything here to them. It
reports, exactly as PHASE-4's validator does, because a retrieval layer that
silently drops a passage is a retrieval layer nobody can debug.

CONTENT GOVERNANCE. `safety_engine.clinical_content_governance` forbids
inventing clinical rules. Every lane, every label and every preferred-evidence
ordering below is copied from persona.txt; the mapping from this product's 21
goals to the spec's 9 question types is stated as data so it can be reviewed
in one place rather than inferred from control flow.

    from src.clinical import evidence
    ranked = evidence.orchestrate(chunks, goal="herb_or_supplement_information")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from . import evidence_class as ec

# ===========================================================================
# The spec's vocabulary, verbatim
# ===========================================================================

# `evidence_system.evidence_question_types`. Order within each tuple is the
# spec's own order and is used as the ranking preference.
QUESTION_TYPES: dict[str, tuple[str, ...]] = {
    "diagnosis": (
        "Diagnostic guidelines",
        "Diagnostic-accuracy studies",
        "Validated clinical criteria",
    ),
    "treatment_benefit": (
        "Current clinical guidelines",
        "Systematic reviews",
        "Randomized controlled trials",
    ),
    "harm_or_interaction": (
        "Regulatory warnings",
        "Official product labels",
        "Pharmacovigilance",
        "Systematic safety reviews",
        "Relevant observational evidence",
    ),
    "prognosis": (
        "Validated prognostic studies",
        "Longitudinal cohort evidence",
        "Guidelines",
    ),
    "screening": (
        "Current population-specific screening guidelines",
    ),
    "patient_education": (
        "Authoritative patient information",
        "Current guidelines",
        "Evidence reviews",
    ),
    "ayurveda_traditional_use": (
        "Authenticated classical sources",
        "Official pharmacopoeial material",
    ),
    "ayurveda_clinical_effectiveness": (
        "Systematic reviews",
        "Controlled clinical studies",
        "Transparent official evidence syntheses",
    ),
    "ayurveda_safety": (
        "Pharmacovigilance",
        "Toxicology",
        "Interaction studies",
        "Product-quality evidence",
        "Regulatory warnings",
    ),
}

# `evidence_system.evidence_lanes`. Lane -> its permitted labels.
LANES: dict[str, tuple[str, ...]] = {
    "modern_medicine": (
        "guideline_supported", "systematic_review", "controlled_trial",
        "observational", "consensus", "insufficient", "conflicting",
    ),
    "ayurveda": (
        "classical_description", "traditional_use", "pharmacopoeial_identity",
        "clinical_evidence", "safety_signal", "insufficient", "conflicting",
    ),
    "nutrition_and_lifestyle": (
        "guideline_supported", "controlled_evidence", "observational",
        "general_wellness", "insufficient",
    ),
    "psychological_and_behavioral": (
        "validated_intervention", "guideline_supported", "self_help_education",
        "requires_professional_care",
    ),
    "physical_rehabilitation_and_yoga": (
        "condition_specific_evidence", "general_mobility",
        "contraindicated_or_caution", "insufficient",
    ),
}

# `evidence_system.cross_lane_rules`, verbatim.
CROSS_LANE_RULES: tuple[str, ...] = (
    "Do not present traditional use as established clinical effectiveness.",
    "Do not equate an Ayurveda concept directly with a modern diagnosis.",
    "Do not hide disagreement between evidence lanes.",
    "Modern emergency assessment and medicine-interaction safety take "
    "precedence over routine wellness discussion.",
    "Allow complementary approaches when their role, evidence and limitations "
    "are clear.",
    "Every personalized claim must be linked to the patient context and "
    "supporting evidence.",
)


# ===========================================================================
# Goal -> question type
#
# Stated as data. Several goals map to `harm_or_interaction` because that is
# what the reader is actually asking, and `cross_lane_rules` puts interaction
# safety above routine discussion — getting this mapping wrong is what makes a
# safety question get answered out of a wellness note.
# ===========================================================================
GOAL_QUESTION_TYPE: dict[str, str] = {
    "new_symptom": "diagnosis",
    "existing_diagnosis": "treatment_benefit",
    "abnormal_lab_result": "diagnosis",
    "report_explanation": "patient_education",
    "medicine_information": "treatment_benefit",
    "personalized_medicine_safety": "harm_or_interaction",
    "herb_or_supplement_information": "ayurveda_traditional_use",
    "personalized_herb_safety": "ayurveda_safety",
    "treatment_options": "treatment_benefit",
    "urgency_or_triage": "diagnosis",
    "preventive_health": "screening",
    "lifestyle_guidance": "patient_education",
    "mental_health": "treatment_benefit",
    "pregnancy_or_reproductive_health": "harm_or_interaction",
    "child_health": "harm_or_interaction",
    "injury_poisoning_or_exposure": "harm_or_interaction",
    "follow_up": "prognosis",
    "second_opinion_preparation": "patient_education",
    "ayurveda_assessment": "ayurveda_traditional_use",
    "general_education": "patient_education",
    "multiple_concerns": "diagnosis",
}

# A question ABOUT effectiveness of an Ayurveda remedy is a different question
# from what tradition says about it, and the spec separates them. The goal
# alone cannot tell them apart, so the wording is consulted too.
_EFFECTIVENESS_RE = re.compile(
    r"\b(work|works|working|effective|effectiveness|efficacy|proven|proof|"
    r"evidence|research|study|studies|trial|cure|cures|asar|faayda|fayda|"
    r"kaam karta|kaam karti|sach me|really)\b", re.IGNORECASE)
_SAFETY_RE = re.compile(
    r"\b(safe|safety|side.?effect|harm|harmful|risk|toxic|toxicity|damage|"
    r"interaction|react|nuksan|nuksaan|khatra|surakshit)\b", re.IGNORECASE)


def question_type_for(goal: str, text: str = "") -> str:
    """Which of the spec's nine question types this turn is asking.

    The goal decides the default; the wording can promote an Ayurveda question
    from `traditional_use` to `clinical_effectiveness` or `safety`, which is
    the distinction `cross_lane_rules` rule 1 exists to protect.
    """
    base = GOAL_QUESTION_TYPE.get(goal or "", "patient_education")
    if base.startswith("ayurveda") and text:
        if _SAFETY_RE.search(text):
            return "ayurveda_safety"
        if _EFFECTIVENESS_RE.search(text):
            return "ayurveda_clinical_effectiveness"
    return base


# ===========================================================================
# Lane and label for a retrieved chunk
#
# Built on `evidence_class.classify_source` so there is ONE place that knows
# what `1-caraka-samhita.pdf` is. This translates that answer into the spec's
# five-lane vocabulary rather than duplicating the source rules.
# ===========================================================================

# The category `evidence_class` assigns -> (lane, label) in the spec's words.
_CATEGORY_TO_LANE: dict[str, tuple[str, str]] = {
    "clinical_guideline": ("modern_medicine", "guideline_supported"),
    "systematic_review_or_meta_analysis": ("modern_medicine", "systematic_review"),
    "randomized_trial": ("modern_medicine", "controlled_trial"),
    "controlled_observational_evidence": ("modern_medicine", "observational"),
    "observational_evidence": ("modern_medicine", "observational"),
    "expert_opinion": ("modern_medicine", "consensus"),
    "mechanistic_or_preclinical_evidence": ("modern_medicine", "insufficient"),
    "classical_primary_text": ("ayurveda", "classical_description"),
    "traditional_practice_or_expert_interpretation": ("ayurveda", "traditional_use"),
    "government_or_standardized_ayurveda_guidance": ("ayurveda", "pharmacopoeial_identity"),
    "clinical_trial": ("ayurveda", "clinical_evidence"),
    "observational_clinical_evidence": ("ayurveda", "clinical_evidence"),
    "pharmacological_or_preclinical_evidence": ("ayurveda", "safety_signal"),
}

# Some material belongs to a lane the source name alone cannot reveal, because
# the lane is about SUBJECT not provenance. Checked against source and text.
_LANE_SUBJECT_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\byoga|asana|pranayam|stretch|physiotherap|exercise|"
                r"mobility|posture\b", re.IGNORECASE),
     "physical_rehabilitation_and_yoga", "general_mobility"),
    (re.compile(r"\b(depress|anxiet|anxious|panic|stress|counsel|therapy|"
                r"cbt|mental.?health|mindful|meditat)\b", re.IGNORECASE),
     "psychological_and_behavioral", "self_help_education"),
    (re.compile(r"\b(diet|nutrition|food|meal|ahar|calorie|vitamin|protein)\b",
                re.IGNORECASE),
     "nutrition_and_lifestyle", "general_wellness"),
]


@dataclass(frozen=True)
class LanedEvidence:
    """One retrieved passage, placed in a lane with a permitted label."""

    source: str = ""
    lane: str = "ayurveda"
    label: str = "insufficient"
    category: str = "unclassified"
    phrase: str = ""
    rank_score: float = 0.0
    retrieval_score: float | None = None
    freshness: str = "unknown"
    text: str = ""

    def as_dict(self) -> dict:
        return {
            "source": self.source, "lane": self.lane, "label": self.label,
            "category": self.category, "rank_score": round(self.rank_score, 3),
            "freshness": self.freshness,
        }


def lane_for(source: str, text: str = "") -> tuple[str, str]:
    """(lane, label) for one passage.

    Provenance decides first — a passage in the Caraka Samhita that mentions
    food is still a classical description, and calling it nutrition advice is
    exactly the equivalence `cross_lane_rules` rule 2 forbids. Only material
    the source rules could not place is routed by subject.
    """
    classification = ec.classify_source(source or "")
    if classification.category == "patient_document":
        # Not evidence about a treatment at all. `evidence_class` already
        # makes this distinction; keep it.
        return "modern_medicine", "insufficient"
    if classification.category != "unclassified":
        return _CATEGORY_TO_LANE.get(
            classification.category, ("ayurveda", "insufficient"))
    haystack = f"{source} {text}"
    for pattern, lane, label in _LANE_SUBJECT_RULES:
        if pattern.search(haystack):
            return lane, label
    return "ayurveda", "insufficient"


# ===========================================================================
# Ranking — the point of the phase
#
# Each of the spec's `preferred_evidence` phrases is matched to the labels that
# actually satisfy it. A source whose label appears earlier in the question
# type's preference list ranks higher FOR THAT QUESTION, which is how
# "authenticated classical sources" can outrank a trial for a question about
# traditional use, and lose to it for a question about effectiveness.
# ===========================================================================
_PREFERENCE_LABELS: dict[str, tuple[str, ...]] = {
    "Diagnostic guidelines": ("guideline_supported",),
    "Diagnostic-accuracy studies": ("systematic_review", "controlled_trial"),
    "Validated clinical criteria": ("guideline_supported", "consensus"),
    "Current clinical guidelines": ("guideline_supported",),
    "Systematic reviews": ("systematic_review",),
    "Randomized controlled trials": ("controlled_trial",),
    "Regulatory warnings": ("guideline_supported", "pharmacopoeial_identity"),
    "Official product labels": ("pharmacopoeial_identity",),
    "Pharmacovigilance": ("safety_signal", "observational"),
    "Systematic safety reviews": ("systematic_review",),
    "Relevant observational evidence": ("observational",),
    "Validated prognostic studies": ("systematic_review", "controlled_trial"),
    "Longitudinal cohort evidence": ("observational",),
    "Guidelines": ("guideline_supported",),
    "Current population-specific screening guidelines": ("guideline_supported",),
    "Authoritative patient information": ("guideline_supported", "consensus",
                                          "self_help_education"),
    "Current guidelines": ("guideline_supported",),
    "Evidence reviews": ("systematic_review",),
    "Authenticated classical sources": ("classical_description",),
    "Official pharmacopoeial material": ("pharmacopoeial_identity",),
    "Controlled clinical studies": ("clinical_evidence", "controlled_trial"),
    "Transparent official evidence syntheses": ("systematic_review",
                                                "pharmacopoeial_identity"),
    "Toxicology": ("safety_signal",),
    "Interaction studies": ("safety_signal", "clinical_evidence"),
    "Product-quality evidence": ("pharmacopoeial_identity",),
}

# What a label is worth when the question type does not name it at all. Small,
# so that ANY preferred match beats any non-preferred one, but not zero: an
# unrelated guideline is still better than an unclassified fragment.
_RESIDUAL = {
    "guideline_supported": 0.9, "systematic_review": 0.8,
    "controlled_trial": 0.7, "clinical_evidence": 0.65,
    "validated_intervention": 0.65, "pharmacopoeial_identity": 0.6,
    "condition_specific_evidence": 0.6, "observational": 0.5,
    "controlled_evidence": 0.5, "consensus": 0.4,
    "classical_description": 0.4, "traditional_use": 0.35,
    "safety_signal": 0.35, "self_help_education": 0.3,
    "general_mobility": 0.25, "general_wellness": 0.25,
    "requires_professional_care": 0.2, "contraindicated_or_caution": 0.2,
    "conflicting": 0.15, "insufficient": 0.1,
}

_PREFERRED_BASE = 10.0  # A preferred label always outranks a residual one.


def preference_score(label: str, question_type: str) -> float:
    """How well `label` answers a question of this type. Higher is better."""
    preferences = QUESTION_TYPES.get(question_type, ())
    for position, preference in enumerate(preferences):
        if label in _PREFERENCE_LABELS.get(preference, ()):
            # Earlier in the spec's list => higher score.
            return _PREFERRED_BASE + (len(preferences) - position)
    return _RESIDUAL.get(label, 0.1)


# ===========================================================================
# Freshness
#
# `evidence_freshness` is a PHASE-5 deliverable. We only claim what we can
# actually observe: a year in the source name or metadata. Anything else is
# reported as "unknown" rather than guessed — a fabricated freshness label is
# worse than an absent one.
# ===========================================================================
_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")

# Classical texts are not stale for what they are cited for. Marking the
# Caraka Samhita "outdated" would be a category error, so provenance decides.
_TIMELESS_LABELS = {"classical_description", "traditional_use",
                    "pharmacopoeial_identity"}


def freshness_of(source: str, label: str = "", metadata: dict | None = None,
                 today: date | None = None) -> str:
    """`current`, `aging`, `outdated`, `timeless`, or `unknown`."""
    if label in _TIMELESS_LABELS:
        return "timeless"
    year = None
    meta = metadata or {}
    for key in ("year", "published", "date", "published_year"):
        raw = meta.get(key)
        if raw:
            found = _YEAR_RE.search(str(raw))
            if found:
                year = int(found.group(1))
                break
    if year is None:
        found = _YEAR_RE.search(source or "")
        if found:
            year = int(found.group(1))
    if year is None:
        return "unknown"
    now = (today or datetime.now().date()).year
    age = now - year
    if age <= 5:
        return "current"
    if age <= 10:
        return "aging"
    return "outdated"


# ===========================================================================
# Conflict retrieval — `cross_lane_rules` rule 3
# ===========================================================================
_CONTRADICTS = re.compile(
    r"\b(no benefit|not effective|ineffective|insufficient evidence|"
    r"no evidence|not recommended|avoid|contraindicated|should not|"
    r"do not use|harmful|unsafe|no significant)\b", re.IGNORECASE)
_SUPPORTS = re.compile(
    r"\b(effective|beneficial|improves|improved|recommended|helps|helpful|"
    r"reduces|significant improvement|useful|indicated)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Conflict:
    """A disagreement that must be shown to the reader, not resolved silently."""

    kind: str = "cross_lane"
    lanes: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    detail: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "lanes": list(self.lanes),
                "sources": list(self.sources), "detail": self.detail}


def detect_conflicts(laned: list[LanedEvidence]) -> list[Conflict]:
    """Where the retrieved evidence disagrees with itself.

    Two shapes are reported. WITHIN a lane, one passage saying a thing helps
    and another saying it does not. ACROSS lanes, tradition recommending what
    modern evidence advises against — the case `cross_lane_rules` rule 1 and
    rule 3 are both about, and the one this product must never average away.
    """
    conflicts: list[Conflict] = []
    stances: dict[str, dict[str, list[str]]] = {}
    for item in laned:
        body = item.text or ""
        contradicts = bool(_CONTRADICTS.search(body))
        # NEGATION FIRST. "not recommended" contains "recommended", so testing
        # support against the raw text makes every negative passage look like
        # it says both things at once — and a passage that says both is
        # discarded as having no stance, which silently hides exactly the
        # disagreement `cross_lane_rules` rule 3 requires us to show.
        supports = bool(_SUPPORTS.search(_CONTRADICTS.sub(" ", body)))
        if supports == contradicts:
            continue  # silent, or genuinely says both — not a usable stance
        stance = "supports" if supports else "contradicts"
        stances.setdefault(item.lane, {}).setdefault(stance, []).append(item.source)

    for lane, byside in stances.items():
        if len(byside) > 1:
            conflicts.append(Conflict(
                kind="within_lane", lanes=(lane,),
                sources=tuple(byside.get("supports", []) + byside.get("contradicts", [])),
                detail=f"Sources within {lane} disagree."))

    lanes_supporting = {l for l, s in stances.items() if "supports" in s}
    lanes_against = {l for l, s in stances.items() if "contradicts" in s}
    for lane_a in sorted(lanes_supporting):
        for lane_b in sorted(lanes_against - {lane_a}):
            conflicts.append(Conflict(
                kind="cross_lane", lanes=(lane_a, lane_b),
                sources=tuple(stances[lane_a]["supports"]
                              + stances[lane_b]["contradicts"]),
                detail=f"{lane_a} suggests benefit where {lane_b} does not."))
    return conflicts


# ===========================================================================
# Citation validation — a PHASE-5 deliverable, and a PHASE-4 concern
# ===========================================================================
_CITATION_RE = re.compile(
    r"\b(?:according to|per|as per|source:|from)\s+"
    r"([A-Z][\w' .-]{2,60}?)(?=[,.;:)\n]|$)", re.IGNORECASE)

# Claims of a study existing. If nothing in the retrieved set is a study, a
# sentence like this is invented — PERSONA_CORE rule 8.
_STUDY_CLAIM_RE = re.compile(
    r"\b(a |one |recent |the )?(study|trial|research paper|meta.?analysis|"
    r"systematic review) (found|showed|shows|proved|proves|concluded|"
    r"demonstrated)\b", re.IGNORECASE)

_STUDY_LABELS = {"systematic_review", "controlled_trial", "clinical_evidence",
                 "observational", "controlled_evidence",
                 "condition_specific_evidence", "validated_intervention"}


@dataclass(frozen=True)
class CitationIssue:
    kind: str = ""
    detail: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail}


def validate_citations(text: str, laned: list[LanedEvidence]) -> list[CitationIssue]:
    """Every source the answer names must be one that was actually retrieved.

    Reports; never edits. A citation the reader can follow to nothing is the
    most expensive kind of wrong in a health product, but so is a regex that
    quietly deletes half a sentence, which this codebase has already learned.
    """
    issues: list[CitationIssue] = []
    body = text or ""
    haystack = " ".join(
        f"{item.source} {item.text}" for item in laned).lower()

    for match in _CITATION_RE.finditer(body):
        named = match.group(1).strip()
        if len(named) < 3:
            continue
        stem = named.lower().split()[0]
        if stem and stem not in haystack:
            issues.append(CitationIssue(
                kind="unretrieved_source",
                detail=f"Names {named!r}, which is not in the retrieved evidence."))

    if _STUDY_CLAIM_RE.search(body):
        if not any(item.label in _STUDY_LABELS for item in laned):
            issues.append(CitationIssue(
                kind="unsupported_study_claim",
                detail="Claims a study found something, but no study was retrieved."))
    return issues


# ===========================================================================
# GraphRAG query improvement — a PHASE-5 deliverable
# ===========================================================================

# Words that carry no retrieval signal. Kept small and non-clinical on
# purpose: dropping a symptom word to "clean" a query is how retrieval starts
# missing the thing the reader actually asked about.
_STOPWORDS = {
    "what", "whats", "is", "are", "the", "a", "an", "of", "for", "to", "do",
    "does", "did", "can", "could", "should", "would", "i", "me", "my", "mujhe",
    "mera", "meri", "kya", "hai", "hain", "ka", "ki", "ke", "ko", "me", "mein",
    "aur", "please", "tell", "about", "batao", "bta", "btao", "bataiye",
    "sakta", "sakti", "hoon", "hu", "and", "or", "in", "on", "it", "this",
}

# What each question type wants the retriever to look for, in the corpus's own
# words. Appended, never substituted: the reader's words always stay.
_QUERY_HINTS: dict[str, tuple[str, ...]] = {
    "diagnosis": ("symptoms", "causes", "diagnosis"),
    "treatment_benefit": ("treatment", "management", "benefit"),
    "harm_or_interaction": ("safety", "side effects", "interaction", "contraindication"),
    "prognosis": ("course", "outlook", "recovery"),
    "screening": ("prevention", "screening", "risk factors"),
    "patient_education": ("overview", "explanation"),
    "ayurveda_traditional_use": ("classical", "traditional use", "indications"),
    "ayurveda_clinical_effectiveness": ("clinical study", "effectiveness", "trial"),
    "ayurveda_safety": ("safety", "toxicity", "adverse", "interaction"),
}


def build_query(text: str, question_type: str = "patient_education",
                problem: str = "", max_terms: int = 24) -> str:
    """A retrieval query shaped by what is being asked.

    The reader's own words come first and are never dropped — a query rewritten
    into the retriever's vocabulary is a query that no longer matches what they
    said. The hints are additive, and the named problem is included so a
    follow-up turn ("and for that?") still retrieves about the right thing.
    """
    words = [w for w in re.findall(r"[\w'-]+", text or "") if w]
    kept = [w for w in words if w.lower() not in _STOPWORDS]
    if not kept:
        kept = words  # never return an empty query
    parts = list(kept[:max_terms])
    if problem:
        for token in re.findall(r"[\w'-]+", problem):
            if token.lower() not in _STOPWORDS and token.lower() not in {
                    p.lower() for p in parts}:
                parts.append(token)
    for hint in _QUERY_HINTS.get(question_type, ()):
        if hint.lower() not in " ".join(parts).lower():
            parts.append(hint)
    return " ".join(parts).strip()


# ===========================================================================
# The orchestrator
# ===========================================================================


@dataclass
class EvidenceSet:
    """Everything PHASE-5 decided about this turn's evidence."""

    question_type: str = "patient_education"
    items: list[LanedEvidence] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    lanes_present: list[str] = field(default_factory=list)
    query: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.items

    def by_lane(self) -> dict[str, list[LanedEvidence]]:
        """Lanes kept SEPARATE, which is the deliverable's whole point."""
        out: dict[str, list[LanedEvidence]] = {}
        for item in self.items:
            out.setdefault(item.lane, []).append(item)
        return out

    def as_dict(self) -> dict:
        return {
            "question_type": self.question_type,
            "lanes_present": list(self.lanes_present),
            "items": [i.as_dict() for i in self.items],
            "conflicts": [c.as_dict() for c in self.conflicts],
        }


def orchestrate(chunks, goal: str = "", text: str = "",
                question_type: str | None = None,
                today: date | None = None) -> EvidenceSet:
    """Rank, lane, date and cross-check the retrieved evidence for this turn.

    Nothing is discarded. Low-ranked material stays in the set, at the bottom,
    so that a caller can see what was available and a log can show why the top
    passage won.
    """
    qtype = question_type or question_type_for(goal, text)
    items: list[LanedEvidence] = []
    for chunk in chunks or []:
        source = getattr(chunk, "source", "") or ""
        body = getattr(chunk, "text", "") or ""
        metadata = getattr(chunk, "metadata", None) or {}
        lane, label = lane_for(source, body)
        classification = ec.classify_source(source)
        items.append(LanedEvidence(
            source=source, lane=lane, label=label,
            category=classification.category, phrase=classification.phrase,
            rank_score=preference_score(label, qtype),
            retrieval_score=getattr(chunk, "score", None),
            freshness=freshness_of(source, label, metadata, today),
            text=body,
        ))

    # Preferred-for-this-question first; retrieval score breaks ties, so the
    # semantic match still matters within a band.
    items.sort(key=lambda i: (i.rank_score, i.retrieval_score or 0.0),
               reverse=True)

    lanes_present: list[str] = []
    for item in items:
        if item.lane not in lanes_present:
            lanes_present.append(item.lane)

    return EvidenceSet(
        question_type=qtype, items=items,
        conflicts=detect_conflicts(items), lanes_present=lanes_present,
        query=build_query(text, qtype),
    )


def describe(evidence_set: EvidenceSet) -> str:
    """One block for the prompt: what each lane holds, and where they disagree.

    Deliberately short and deliberately explicit about insufficiency. Silence
    about a gap reads as confidence, which is the failure `PERSONA_CORE` rule 8
    and `response_validator.no_false_certainty` both guard.
    """
    if evidence_set.is_empty:
        return ("EVIDENCE: nothing relevant was retrieved. Say plainly that you "
                "do not have reliable material on this, and do not imply "
                "research support for anything.")
    lines = [f"EVIDENCE for a {evidence_set.question_type.replace('_', ' ')} question:"]
    for lane, entries in evidence_set.by_lane().items():
        best = entries[0]
        labels = ", ".join(sorted({e.label for e in entries}))
        lines.append(f"- {lane}: {labels}. Introduce as: {best.phrase}.")
    for conflict in evidence_set.conflicts:
        lines.append(f"- DISAGREEMENT ({conflict.kind}): {conflict.detail} "
                     "Say so plainly; do not pick a side silently.")
    lines.append("Never present traditional use as proven clinical effect.")
    return "\n".join(lines)
