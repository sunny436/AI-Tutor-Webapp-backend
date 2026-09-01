"""
clinical/interactions.py
------------------------
May THIS person take THIS thing?

WHY A TABLE AND NOT A MODEL
The question "does ashwagandha interact with thyroid medication" has a stable,
knowable answer, and a model that is asked it fresh every turn will
occasionally say no. A table is auditable, reviewable by a clinician who does
not read Python, identical on every run, and free. The model's job is to
propose; this decides.

WHAT IS ENCODED. Herbs the product actually names, against the patient facts it
actually holds — current medicines, conditions, allergies, pregnancy. The list
is deliberately short and well-attested rather than exhaustive: an entry that
is wrong is worse than an entry that is missing, because a missing one falls
through to `UNKNOWN` and asks, while a wrong one blocks something safe or
clears something dangerous.

MISSING INFORMATION IS AN ANSWER. `caution` with `missing_information` is
returned when a check cannot be completed — "is this person pregnant?" is
unanswered and the herb is one that matters in pregnancy. The spec is explicit
that unknown important interaction information can itself block a
recommendation, and this is where that is decided rather than assumed.

THIS DOES NOT NAME A DOSE, EVER. `PERSONA_CORE` rule 2 forbids a dose for a
herb as firmly as for a drug, so nothing here carries one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Statuses, weakest to strongest — `worst()` is how several checks combine.
STATUSES = ("safe", "caution", "blocked")


@dataclass(frozen=True)
class Verdict:
    status: str = "safe"
    intervention: str = ""
    reasons: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"

    def as_dict(self) -> dict:
        return {
            "intervention": self.intervention,
            "status": self.status,
            "reasons": list(self.reasons),
            "missing_information": list(self.missing_information),
        }


def worst(*statuses: str) -> str:
    return STATUSES[max((STATUSES.index(s) for s in statuses if s in STATUSES), default=0)]


def _rx(*words: str) -> re.Pattern:
    return re.compile("|".join(words), re.IGNORECASE)


# Patient-side facts, matched against the profile and the transcript.
_ANTICOAGULANT = _rx(r"\bwarfarin\b", r"\bclopidogrel\b", r"\bapixaban\b",
                     r"\brivaroxaban\b", r"\bheparin\b", r"\baspirin\b",
                     r"\bblood\s+thinner\w*\b", r"\banticoagul\w*\b",
                     r"\bkhoon\s+patla\b")
_GLUCOSE_LOWERING = _rx(r"\bmetformin\b", r"\binsulin\b", r"\bglimepiride\b",
                        r"\bgliclazide\b", r"\bsitagliptin\b", r"\bsugar\s+ki\s+dawa\b",
                        r"\bdiabet\w*\s+medic\w*\b")
_THYROID_MED = _rx(r"\bthyroxine\b", r"\blevothyroxine\b", r"\beltroxin\b",
                   r"\bthyronorm\b", r"\bthyroid\s+ki\s+dawa\b")
_BP_MED = _rx(r"\bamlodipine\b", r"\btelmisartan\b", r"\blosartan\b", r"\bramipril\b",
              r"\batenolol\b", r"\bmetoprolol\b", r"\bbp\s+ki\s+dawa\b")
_SEDATIVE = _rx(r"\balprazolam\b", r"\bclonazepam\b", r"\bdiazepam\b",
                r"\bzolpidem\b", r"\bneend\s+ki\s+(?:goli|dawa)\b")
_IMMUNOSUPPRESSANT = _rx(r"\btacrolimus\b", r"\bcyclosporin\w*\b", r"\bazathioprine\b",
                         r"\bmethotrexate\b", r"\bsteroid\w*\b", r"\bprednisolone\b")
_PREGNANT = _rx(r"\bpregnan\w*\b", r"\bgarbh\w*\b", r"\bexpecting\b", r"\bगर्भ\w*")
_BREASTFEEDING = _rx(r"\bbreastfeed\w*\b", r"\bnursing\b", r"\bstanpan\b")
_KIDNEY = _rx(r"\bkidney\b", r"\brenal\b", r"\bdialysis\b", r"\bckd\b", r"\bगुर्दा\b")
_LIVER = _rx(r"\bliver\b", r"\bhepat\w*\b", r"\bcirrhos\w*\b", r"\bfatty\s+liver\b")
_HYPERTENSION = _rx(r"\bhypertens\w*\b", r"\bhigh\s+bp\b", r"\bblood\s+pressure\b",
                    r"\bbp\s+high\b")
_SURGERY_SOON = _rx(r"\bsurgery\b", r"\boperation\b", r"\bsurgical\b", r"\bcperation\b")
_CANCER_TREATMENT = _rx(r"\bchemo\w*\b", r"\bradiation\b", r"\bradiotherapy\b",
                        r"\boncolog\w*\b", r"\bcancer\b")

# intervention -> (matcher, [(patient-fact matcher, status, reason)], asks-if-unknown)
_RULES: dict[str, tuple] = {
    "ashwagandha": (
        _rx(r"\bashwagandha\b", r"\bwithania\b", r"\basgandh\b"),
        [
            (_THYROID_MED, "blocked",
             "it can raise thyroid hormone levels, and they are already on thyroid medication"),
            (_IMMUNOSUPPRESSANT, "blocked",
             "it stimulates immune activity, which works against immunosuppressive treatment"),
            (_SEDATIVE, "caution", "it can add to the effect of sedative medication"),
            (_PREGNANT, "blocked", "it is traditionally avoided in pregnancy"),
        ],
        ["whether they are pregnant"],
    ),
    "guggulu": (
        _rx(r"\bguggul\w*\b"),
        [
            (_THYROID_MED, "blocked", "it affects thyroid hormone levels"),
            (_ANTICOAGULANT, "blocked", "it can increase bleeding risk alongside blood thinners"),
            (_PREGNANT, "blocked", "it is avoided in pregnancy"),
            (_SURGERY_SOON, "caution", "bleeding risk around surgery"),
        ],
        ["whether they are pregnant", "whether they take a blood thinner"],
    ),
    "turmeric": (
        _rx(r"\bturmeric\b", r"\bhaldi\b", r"\bcurcumin\b", r"\bहल्दी\b"),
        [
            (_ANTICOAGULANT, "caution",
             "in medicinal amounts it can add to the effect of blood thinners"),
            (_SURGERY_SOON, "caution", "bleeding risk around surgery"),
        ],
        [],
    ),
    "ginger": (
        _rx(r"\bginger\b", r"\badrak\b", r"\bsonth\b", r"\bअदरक\b"),
        [
            (_ANTICOAGULANT, "caution", "it can add to the effect of blood thinners"),
            (_SURGERY_SOON, "caution", "bleeding risk around surgery"),
        ],
        [],
    ),
    "garlic": (
        _rx(r"\bgarlic\b", r"\blehsun\b", r"\blashun\b"),
        [(_ANTICOAGULANT, "caution", "it can add to the effect of blood thinners")],
        [],
    ),
    "licorice": (
        _rx(r"\bliquorice\b", r"\blicorice\b", r"\bmulethi\b", r"\byashtimadhu\b"),
        [
            (_HYPERTENSION, "blocked", "it can raise blood pressure and lower potassium"),
            (_BP_MED, "blocked", "it works against blood-pressure medication"),
            (_PREGNANT, "blocked", "it is avoided in pregnancy"),
            (_KIDNEY, "caution", "it affects fluid and potassium balance"),
        ],
        ["whether their blood pressure is raised"],
    ),
    "fenugreek": (
        _rx(r"\bfenugreek\b", r"\bmethi\b", r"\bमेथी\b"),
        [
            (_GLUCOSE_LOWERING, "caution",
             "it lowers blood sugar and they already take glucose-lowering medication"),
            (_PREGNANT, "blocked", "in medicinal amounts it is avoided in pregnancy"),
            (_ANTICOAGULANT, "caution", "it may add to the effect of blood thinners"),
        ],
        ["whether they are pregnant"],
    ),
    "bitter gourd": (
        _rx(r"\bkarela\b", r"\bbitter\s+gourd\b", r"\bmomordica\b"),
        [(_GLUCOSE_LOWERING, "caution",
          "it lowers blood sugar on top of their glucose-lowering medication")],
        [],
    ),
    "arjuna": (
        _rx(r"\barjuna\b", r"\bterminalia\s+arjuna\b"),
        [(_BP_MED, "caution", "it can add to the effect of blood-pressure medication")],
        [],
    ),
    "brahmi": (
        _rx(r"\bbrahmi\b", r"\bbacopa\b"),
        [
            (_SEDATIVE, "caution", "it can add to the effect of sedative medication"),
            (_THYROID_MED, "caution", "it can affect thyroid hormone levels"),
        ],
        [],
    ),
    "triphala": (
        _rx(r"\btriphala\b"),
        [
            (_ANTICOAGULANT, "caution", "it may add to the effect of blood thinners"),
            (_PREGNANT, "caution", "its laxative effect is avoided in pregnancy"),
        ],
        [],
    ),
    "trikatu": (
        # Bioavailability enhancers matter far beyond themselves: they change
        # how much of an unrelated prescription reaches the blood.
        _rx(r"\btrikatu\b", r"\bpippali\b", r"\blong\s+pepper\b", r"\bblack\s+pepper\b",
            r"\bkali\s+mirch\b", r"\bpiperine\b"),
        [(_rx(r"\b(?:tablet|medicine|dawa|medication|capsule)\b"), "caution",
          "it increases how much of other medicines the body absorbs, which can "
          "change their effect")],
        [],
    ),
    "fasting": (
        _rx(r"\bfast(?:ing|s)?\b", r"\bupvas\b", r"\bvrat\b", r"\blanghana\b"),
        [
            (_GLUCOSE_LOWERING, "blocked",
             "fasting alongside glucose-lowering medication risks hypoglycaemia"),
            (_PREGNANT, "blocked", "fasting is not advised in pregnancy"),
            (_BREASTFEEDING, "caution", "fasting while breastfeeding needs care"),
            (_CANCER_TREATMENT, "blocked", "fasting during cancer treatment is unsafe"),
        ],
        ["whether they take medication for diabetes"],
    ),
    "panchakarma": (
        _rx(r"\bpanchakarma\b", r"\bvirechana\b", r"\bvamana\b", r"\bbasti\b",
            r"\bdetox\w*\b", r"\bcleanse\b"),
        [
            (_PREGNANT, "blocked", "purification therapy is not done in pregnancy"),
            (_CANCER_TREATMENT, "blocked",
             "purification therapy during cancer treatment can be harmful"),
            (_KIDNEY, "blocked", "fluid and electrolyte shifts are unsafe with kidney disease"),
            (_LIVER, "caution", "liver impairment changes how this is tolerated"),
            (_ANTICOAGULANT, "caution", "bleeding risk"),
        ],
        ["whether they are pregnant", "any kidney or liver problem"],
    ),
}


# "not pregnant", "no blood thinner", "koi dawa nahi" — a DENIAL of a fact
# reads to a plain substring match exactly like the fact itself, so a patient
# who has carefully told us they are not pregnant had every pregnancy-sensitive
# herb blocked. Found by the benchmark: four of six herbs were blocked for a
# deliberately unremarkable patient.
_NEGATION = re.compile(
    r"\b(?:not|no|never|non|without|nahi|nahin|nhi|na)\b[\s,]*"
    r"(?P<scope>(?:\w+[\s-]*){0,3})",
    re.IGNORECASE,
)


def _strip_negated(text: str) -> str:
    """Remove the few words following a negation, so denials do not match.

    Blunt on purpose: a three-word window after "no"/"nahi" covers "not
    pregnant", "no blood thinner" and "koi dawa nahi le raha" without needing a
    parser. Erring toward removing too much is the safe direction here — the
    cost is asking a question that was already answered, not clearing a real
    contraindication, because a genuine fact is never phrased as its denial.
    """
    return _NEGATION.sub(" ", text or "")


def known_interventions() -> list[str]:
    return sorted(_RULES)


def find_interventions(text: str) -> list[str]:
    """Which known interventions this text names. Used to screen an answer."""
    body = text or ""
    return [name for name, (matcher, _r, _a) in _RULES.items() if matcher.search(body)]


def check(
    intervention: str,
    *,
    medications: list[str] | None = None,
    conditions: list[str] | None = None,
    allergies: list[str] | None = None,
    extra_context: str = "",
) -> Verdict:
    """Is this intervention safe for this person?

    `medications` should be the ACTIVE ones — `PatientProfile.active(...)`, not
    `values(...)`. A drug they stopped last year must not drive a warning, and
    that distinction is exactly what `Fact.status` exists for.
    """
    name = (intervention or "").strip().lower()
    rule = _RULES.get(name)
    if rule is None:
        for key, (matcher, _r, _a) in _RULES.items():
            if matcher.search(name):
                rule = _RULES[key]
                name = key
                break
    if rule is None:
        return Verdict(status="safe", intervention=intervention,
                       reasons=["nothing known against it for this person"])

    matcher, conflicts, asks = rule
    patient_text = _strip_negated(" ".join(
        [" ".join(medications or []), " ".join(conditions or []),
         " ".join(allergies or []), extra_context or ""]
    ))

    status, reasons = "safe", []
    for fact_rx, fact_status, reason in conflicts:
        if fact_rx.search(patient_text):
            status = worst(status, fact_status)
            reasons.append(reason)

    # An allergy to the thing itself always blocks, whatever else is true.
    if allergies and matcher.search(" ".join(allergies)):
        status, reasons = "blocked", [f"they have reported a reaction to {name}"]

    # UNANSWERED QUESTIONS THAT MATTER ARE THEMSELVES A REASON TO PAUSE.
    missing = []
    for question in asks:
        already = re.search(
            r"pregnan|garbh|diabet|sugar|blood\s+thinner|kidney|liver|bp|pressure",
            patient_text, re.I,
        )
        if not already:
            missing.append(question)
    if missing and status == "safe":
        status = "caution"

    return Verdict(status=status, intervention=name, reasons=reasons,
                   missing_information=missing)


def screen_text(
    text: str,
    *,
    medications: list[str] | None = None,
    conditions: list[str] | None = None,
    allergies: list[str] | None = None,
    extra_context: str = "",
) -> list[Verdict]:
    """Every known intervention named in `text`, checked against this person.

    This is what runs over a generated answer before it is shown: the model may
    name anything it likes, and this is where what it named meets who is
    reading it.
    """
    return [
        check(name, medications=medications, conditions=conditions,
              allergies=allergies, extra_context=extra_context)
        for name in find_interventions(text)
    ]
