"""
clinical/evidence_class.py
--------------------------
What KIND of evidence is this, and how may it be spoken about?

THE FAILURE THIS PREVENTS
A sentence from the Caraka Samhita and a randomised trial both arrive as a
`Chunk` with some text and a filename. Handed to a model together they are
indistinguishable, and it will write "research shows" over a classical
description — which is the single most damaging thing an Ayurveda product can
do to its own credibility, and the reason `PERSONA_CORE` rule 8 forbids
inventing a study.

So every chunk gets a category, and every category gets the words it is allowed
to be introduced with. "Traditionally described" and "clinical evidence
suggests" are not stylistic choices; they are claims of different strength, and
which one is permitted is decided here rather than by the model.

CLASSIFIED BY SOURCE, NOT BY READING THE TEXT. The corpus is small and known,
so the filename is a reliable, auditable signal — `1-caraka-samhita.pdf` is a
classical primary text whatever any individual passage says. Guessing from the
prose would be both slower and less certain, and would let a passage that
merely QUOTES a trial promote itself.

`retrieval/` deliberately does not import this: retrievers fetch, this
interprets. See `consult/evidence.py` for the separate question of whether a
SECTION has any support at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Strongest first. Order is the API: `strongest_of` sorts by it, and the
# introduction the reader sees comes from the best category present.
MODERN_CATEGORIES = (
    "clinical_guideline",
    "systematic_review_or_meta_analysis",
    "randomized_trial",
    "controlled_observational_evidence",
    "observational_evidence",
    "mechanistic_or_preclinical_evidence",
    "expert_opinion",
)
AYURVEDA_CATEGORIES = (
    "government_or_standardized_ayurveda_guidance",
    "systematic_review_or_meta_analysis",
    "clinical_trial",
    "observational_clinical_evidence",
    "pharmacological_or_preclinical_evidence",
    "classical_primary_text",
    "traditional_practice_or_expert_interpretation",
)

# How much weight a category may be given when several are present. This is
# NOT the same as the ordering above: a classical text is authoritative about
# tradition and says nothing about clinical effect, so it ranks low here and
# high in what it is allowed to be called.
_WEIGHT = {
    "clinical_guideline": 90,
    "systematic_review_or_meta_analysis": 85,
    "randomized_trial": 75,
    "clinical_trial": 70,
    "controlled_observational_evidence": 60,
    "observational_clinical_evidence": 55,
    "observational_evidence": 50,
    "government_or_standardized_ayurveda_guidance": 65,
    "pharmacological_or_preclinical_evidence": 30,
    "mechanistic_or_preclinical_evidence": 30,
    "classical_primary_text": 40,
    "traditional_practice_or_expert_interpretation": 25,
    "expert_opinion": 20,
    "patient_document": 0,
    "unclassified": 10,
}

# How each category may be introduced. The mapping the spec asks for, made
# concrete: these strings are what a composer is permitted to say.
_PHRASE = {
    "classical_primary_text": "Traditionally described",
    "traditional_practice_or_expert_interpretation": "Traditionally described",
    "government_or_standardized_ayurveda_guidance": "Standard Ayurveda guidance describes",
    "pharmacological_or_preclinical_evidence": "Early laboratory work suggests",
    "mechanistic_or_preclinical_evidence": "Early laboratory work suggests",
    "observational_clinical_evidence": "Limited clinical evidence suggests",
    "observational_evidence": "Limited clinical evidence suggests",
    "controlled_observational_evidence": "Limited clinical evidence suggests",
    "clinical_trial": "Clinical evidence suggests",
    "randomized_trial": "Clinical evidence suggests",
    "systematic_review_or_meta_analysis": "Clinical evidence supports",
    "clinical_guideline": "Clinical guidelines recommend",
    "expert_opinion": "Practitioners commonly suggest",
    "patient_document": "Your own report records",
    "unclassified": "Reliable evidence is currently insufficient to say",
}

TRADITION = "ayurveda"
MODERN = "modern"


@dataclass(frozen=True)
class Classification:
    category: str = "unclassified"
    tradition: str = TRADITION
    source: str = ""
    phrase: str = ""
    weight: int = 0

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "category": self.category,
            "tradition": self.tradition,
            "phrase": self.phrase,
            "weight": self.weight,
        }


# Source patterns -> (category, tradition). Ordered: first match wins, so the
# specific classical texts are listed before the generic Ayurveda catch-all.
_SOURCE_RULES: list[tuple[re.Pattern, str, str]] = [
    # The patient's OWN uploaded report. Fact about them, never evidence about
    # a treatment — `_GROUNDING_RULES` rule 12 already gives it that standing.
    (re.compile(r"^report:", re.I), "patient_document", MODERN),
    # The classical corpus, by name.
    (re.compile(r"caraka|charaka|sushruta|susruta|ashtanga|astanga|hridaya|"
                r"sharngadhara|sarngadhara|madhava.?nidana|bhaishajya|"
                r"samhita|nighantu", re.I), "classical_primary_text", TRADITION),
    # Government / standardised guidance.
    (re.compile(r"cross.?referral|guideline|ministry|ayush|ccras|pharmacopoeia|"
                r"standard.?treatment", re.I),
     "government_or_standardized_ayurveda_guidance", TRADITION),
    # Modern research shapes, when such a document is added to the corpus.
    (re.compile(r"meta.?analys|systematic.?review|cochrane", re.I),
     "systematic_review_or_meta_analysis", MODERN),
    (re.compile(r"\brct\b|randomi[sz]ed|randomised.?trial", re.I),
     "randomized_trial", MODERN),
    (re.compile(r"\btrial\b", re.I), "clinical_trial", TRADITION),
    (re.compile(r"cohort|case.?control|observational", re.I),
     "observational_evidence", MODERN),
    (re.compile(r"in.?vitro|in.?vivo|animal|rat|mice|preclinical|pharmacolog",
                re.I), "pharmacological_or_preclinical_evidence", TRADITION),
    # The curated local notes — this product's own editorial voice.
    (re.compile(r"^knowledge:|\.md$", re.I),
     "traditional_practice_or_expert_interpretation", TRADITION),
]


def classify_source(source: str) -> Classification:
    """Category for one source string, as `Chunk.source` carries it."""
    name = (source or "").strip()
    for pattern, category, tradition in _SOURCE_RULES:
        if pattern.search(name):
            return Classification(
                category=category, tradition=tradition, source=name,
                phrase=_PHRASE.get(category, _PHRASE["unclassified"]),
                weight=_WEIGHT.get(category, 10),
            )
    return Classification(
        category="unclassified", tradition=TRADITION, source=name,
        phrase=_PHRASE["unclassified"], weight=_WEIGHT["unclassified"],
    )


def classify_chunks(chunks) -> list[Classification]:
    """Classify an iterable of `retrieval.base.Chunk` (anything with `.source`)."""
    seen, out = set(), []
    for chunk in chunks or []:
        source = getattr(chunk, "source", "") or ""
        if source in seen:
            continue
        seen.add(source)
        out.append(classify_source(source))
    return out


def strongest_of(classifications: list[Classification]) -> Classification | None:
    """The best-supported category present, ignoring the patient's own report.

    The report is excluded because it is not evidence ABOUT a treatment — it
    says what this person's haemoglobin is, not whether a herb works.
    """
    usable = [c for c in classifications if c.category != "patient_document"]
    if not usable:
        return None
    return max(usable, key=lambda c: c.weight)


def describe(classifications: list[Classification]) -> str:
    """One line for the prompt: what may be claimed, and what may not.

    Kept short deliberately. This goes into a prompt that is already long, and
    its whole job is to stop one sentence being written the wrong way.
    """
    best = strongest_of(classifications)
    if best is None:
        return (
            "EVIDENCE: none retrieved. Do not imply research support for anything; "
            "say plainly where reliable evidence is insufficient."
        )
    traditions = {c.tradition for c in classifications if c.category != "patient_document"}
    both = len(traditions) > 1
    line = (
        f"EVIDENCE: the strongest supporting material is "
        f"{best.category.replace('_', ' ')}. "
        f"Introduce claims drawn from it with wording no stronger than "
        f"\"{best.phrase}\"."
    )
    if best.tradition == TRADITION and best.category in (
        "classical_primary_text", "traditional_practice_or_expert_interpretation"
    ):
        line += (
            " This is a traditional description, NOT a clinical finding — do not "
            "write \"research shows\", \"studies prove\" or \"clinically proven\"."
        )
    if both:
        line += (
            " Traditional and modern material are both present: keep them "
            "distinguishable rather than merging them into one claim."
        )
    return line
