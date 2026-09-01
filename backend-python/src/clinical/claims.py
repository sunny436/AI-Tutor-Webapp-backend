"""
clinical/claims.py
------------------
Turn retrieved passages into CLAIMS a recommendation gate can reason about.

WHY A CLAIM AND NOT A PASSAGE
A passage is prose: "Amlapitta is caused by vidahi ahara; sheeta virya dravyas
are indicated; it is contraindicated in..." — one blob carrying an assertion, a
suggestion and a warning at once. Handed to a composer it is all equally
weighted, and the warning is the part that gets dropped. A claim separates
them, so the gate can act on the contraindication and the composer can be told
how strongly the suggestion may be phrased.

THIS DOES NOT REPLACE GRAPHRAG AND IT DOES NOT CALL IT.
`retrieval/graphrag.py` still does the retrieval, still calls `/v1/search`
only, and is untouched. This reads what it returned. GraphRAG NEVER authorises
a treatment: it produces claims, `clinical/gate.py` decides, and the ordering
in `graph.run_turn` puts the triage verdict before retrieval so nothing
retrieved can raise the ceiling.

EXTRACTION IS DETERMINISTIC. No second model call: a per-turn LLM pass over
every chunk would cost more than the answer itself, and a regex that
mis-classifies a sentence is visible and fixable in a way a model's mood is
not. The shapes below are the ones the corpus actually uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.clinical.evidence_class import classify_source

# What a sentence is doing. Ordered by how much the gate cares.
CLAIM_KINDS = ("contraindication", "safety", "intervention", "cause", "descriptive")

_SENTENCE = re.compile(r"[^.!?\n।]+[.!?।]?", re.UNICODE)

_CONTRAINDICATION = re.compile(
    r"\b(?:contraindicat\w*|should\s+not|must\s+not|avoid\w*|not\s+advis\w*|"
    r"unsafe|harmful|nahi\s+karna|na\s+karein|varjit|pathya\s+nahi|apathya)\b",
    re.IGNORECASE,
)
_SAFETY = re.compile(
    r"\b(?:caution|careful|monitor|consult\s+a?\s*(?:doctor|physician|vaidya)|"
    r"seek\s+medical|refer\w*|emergency|warning|dhyan\s+rakh\w*|savdhani)\b",
    re.IGNORECASE,
)
_INTERVENTION = re.compile(
    r"\b(?:indicated|recommend\w*|useful|beneficial|helps?|treat\w*|"
    r"administer\w*|prescrib\w*|is\s+given|pathya|hitkar|labhdayak|"
    r"faydemand|upyogi|should\s+(?:take|be\s+taken|practise|practice))\b",
    re.IGNORECASE,
)
_CAUSE = re.compile(
    r"\b(?:caused\s+by|due\s+to|results?\s+from|leads?\s+to|nidana|hetu|"
    r"karan|because\s+of|arises\s+from)\b",
    re.IGNORECASE,
)

# A dose or quantity anywhere in a claim. Never passed on — PERSONA_CORE
# rule 2 forbids a dose for a herb as firmly as for a drug, so a claim that
# carries one is stripped of it rather than quietly forwarded.
_DOSE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|ml|g|gram|grams|gm|tola|masha|ratti|"
    r"teaspoons?|tsp|tablespoons?|tbsp)\b",
    re.IGNORECASE,
)

MAX_CLAIMS = 24
MIN_CLAIM_CHARS = 30


@dataclass
class Claim:
    text: str = ""
    kind: str = "descriptive"
    source: str = ""
    evidence_category: str = ""
    tradition: str = ""
    phrase: str = ""
    weight: int = 0
    score: float | None = None
    carried_dose: bool = False

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "kind": self.kind,
            "source": self.source,
            "evidence_category": self.evidence_category,
            "tradition": self.tradition,
            "phrase": self.phrase,
            "weight": self.weight,
            "score": self.score,
            "carried_dose": self.carried_dose,
        }


@dataclass
class ClaimSet:
    claims: list[Claim] = field(default_factory=list)

    def of(self, *kinds: str) -> list[Claim]:
        return [c for c in self.claims if c.kind in kinds]

    @property
    def contraindications(self) -> list[Claim]:
        return self.of("contraindication")

    @property
    def safety(self) -> list[Claim]:
        return self.of("safety", "contraindication")

    @property
    def interventions(self) -> list[Claim]:
        return self.of("intervention")

    def contradictions(self) -> list[tuple[Claim, Claim]]:
        """Pairs where one source recommends what another warns against.

        Surfaced rather than resolved. Two traditions genuinely disagreeing is
        information; silently picking the one that reads better is how a
        product develops opinions it cannot defend.
        """
        from src.clinical import interactions

        out = []
        for warn in self.contraindications:
            warn_words = _content_words(warn.text)
            warn_named = set(interactions.find_interventions(warn.text))
            for rec in self.interventions:
                if rec.source == warn.source:
                    continue
                # SHARING THE NAMED INTERVENTION IS ENOUGH. Two content words
                # is the right bar for prose that overlaps by accident, and the
                # wrong one when the whole subject is a single herb: "Guggulu
                # should not be given in pregnancy" and "Guggulu is recommended
                # for kapha disorders" share exactly one word — the only word
                # that matters — and were not being flagged.
                if warn_named & set(interactions.find_interventions(rec.text)):
                    out.append((rec, warn))
                    continue
                if len(warn_words & _content_words(rec.text)) >= 2:
                    out.append((rec, warn))
        return out[:6]

    def as_dict(self) -> dict:
        return {
            "claims": [c.as_dict() for c in self.claims],
            "counts": {k: len(self.of(k)) for k in CLAIM_KINDS},
            "contradictions": [
                {"recommends": r.text[:90], "warns": w.text[:90]}
                for r, w in self.contradictions()
            ],
        }

    def render(self, limit: int = 8) -> str:
        """A prompt block: the safety claims first, then what may be offered."""
        if not self.claims:
            return ""
        lines = []
        for claim in (self.safety + self.interventions)[:limit]:
            tag = claim.kind.upper()
            lines.append(f"  [{tag}] {claim.phrase}: {claim.text[:150]}")
        if not lines:
            return ""
        head = (
            "CLAIMS FOUND IN THE RETRIEVED MATERIAL. A claim is not permission: "
            "anything marked CONTRAINDICATION or SAFETY must be respected even "
            "when another line suggests otherwise."
        )
        clash = self.contradictions()
        if clash:
            head += (
                f" {len(clash)} of these CONTRADICT each other — say so plainly "
                "rather than choosing a side."
            )
        return head + "\n" + "\n".join(lines)


_STOP = {"the", "a", "an", "of", "in", "is", "are", "and", "or", "to", "for",
         "with", "be", "should", "not", "it", "this", "that", "as", "by"}


def _content_words(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in _STOP
    }


def _kind_of(sentence: str) -> str:
    # Ordered: a sentence that both recommends and warns is a WARNING. Reading
    # it the other way is how a contraindication becomes a suggestion.
    if _CONTRAINDICATION.search(sentence):
        return "contraindication"
    if _SAFETY.search(sentence):
        return "safety"
    if _INTERVENTION.search(sentence):
        return "intervention"
    if _CAUSE.search(sentence):
        return "cause"
    return "descriptive"


def from_chunks(chunks) -> ClaimSet:
    """Extract claims from retrieved chunks, carrying provenance on each.

    `chunks` is anything with `.text`, `.source` and optionally `.score` — the
    `retrieval.base.Chunk` shape, passed in rather than imported so this stays
    testable with a plain object.
    """
    claims: list[Claim] = []
    seen: set[str] = set()
    for chunk in chunks or []:
        source = getattr(chunk, "source", "") or ""
        # A patient's own report is fact about them, never evidence about a
        # treatment. `evidence_class` already draws that line; respect it.
        classification = classify_source(source)
        if classification.category == "patient_document":
            continue
        for raw in _SENTENCE.findall(getattr(chunk, "text", "") or ""):
            sentence = " ".join(raw.split())
            if len(sentence) < MIN_CLAIM_CHARS:
                continue
            key = sentence.lower()[:110]
            if key in seen:
                continue
            seen.add(key)
            # Length is checked BEFORE the dose is removed, above, so a short
            # sentence whose only content is a dose is dropped outright rather
            # than forwarded as "(amount removed)" — which is the right
            # outcome, and the reason the floor sits where it does.
            had_dose = bool(_DOSE.search(sentence))
            claims.append(Claim(
                text=_DOSE.sub("(amount removed)", sentence)[:300],
                kind=_kind_of(sentence),
                source=source,
                evidence_category=classification.category,
                tradition=classification.tradition,
                phrase=classification.phrase,
                weight=classification.weight,
                score=getattr(chunk, "score", None),
                carried_dose=had_dose,
            ))
    # Safety first, then by how well supported. A contraindication from a weak
    # source still outranks a recommendation from a strong one.
    order = {k: i for i, k in enumerate(CLAIM_KINDS)}
    claims.sort(key=lambda c: (order.get(c.kind, 9), -c.weight))
    return ClaimSet(claims=claims[:MAX_CLAIMS])
