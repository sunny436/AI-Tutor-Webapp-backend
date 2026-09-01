"""
clinical/reasoning.py
---------------------
Two independent readings of the same person, and an honest account of where
they disagree.

WHY TWO
An Ayurveda product that quietly treats "acidity" and "amlapitta" as the same
word has stopped doing either system properly. They are different frameworks
describing the same patient, they sometimes point the same way and sometimes
do not, and the places they diverge are exactly where a careful practitioner
pays attention. Collapsing them loses that, and it loses it invisibly.

WHAT IS ENFORCED HERE RATHER THAN ASKED FOR
The prompt states the rules; this module makes three of them true regardless of
what came back, because they are the ones that do damage when a model is having
an off day:

  1. PRAKRITI STAYS UNKNOWN unless the conversation actually assessed it. A
     single complaint says nothing about a lifelong constitution. Somebody
     reporting acidity is not "pitta prakriti" — they may have a current pitta
     VIKRITI, which is a different claim about a different timescale.
  2. NO POSSIBILITY BECOMES A DIAGNOSIS. Anything phrased as certainty is
     downgraded to a possibility before it leaves this module.
  3. UNSUPPORTED AYURVEDA CHAINS ARE DROPPED. A samprapti invented to fill a
     field reads exactly like one derived from the case.

`reason()` is the only thing that calls a model. Everything else is pure and
tested without one.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

import config
from src import prompts
from src.consult.repair import extract_json
from src.llm import invoke as llm_invoke

REASONING_TEMPERATURE = 0.3

# Words that turn a possibility into a claim. Checked on the way out.
_CERTAINTY = re.compile(
    r"\b(?:you\s+have|aapko\s+hai|definitely|certainly|confirmed|diagnosed\s+with"
    r"|it\s+is\s+definitely|pakka|nishchit)\b",
    re.IGNORECASE,
)

# A prakriti claim is only believable if the conversation actually assessed it.
# These are the things a real assessment asks about — build, appetite over a
# lifetime, sleep pattern, tolerance of heat and cold, skin, temperament.
_PRAKRITI_EVIDENCE = re.compile(
    r"\b(?:prakriti|prakruti|constitution|since\s+childhood|bachpan\s+se|"
    r"lifelong|hamesha\s+se|always\s+been)\b",
    re.IGNORECASE,
)


@dataclass
class Possibility:
    name: str = ""
    supports: list[str] = field(default_factory=list)
    against: list[str] = field(default_factory=list)
    likelihood: str = "possible"

    def as_dict(self) -> dict:
        return {"name": self.name, "supports": self.supports,
                "against": self.against, "likelihood": self.likelihood}


@dataclass
class ModernReasoning:
    possible_explanations: list[Possibility] = field(default_factory=list)
    must_not_miss: list[dict] = field(default_factory=list)
    medication_contributors: list[str] = field(default_factory=list)
    lifestyle_contributors: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    suggested_evaluation: list[str] = field(default_factory=list)
    uncertainty: str = "moderate"
    safe_scope: str = ""

    def as_dict(self) -> dict:
        return {
            "possible_explanations": [p.as_dict() for p in self.possible_explanations],
            "must_not_miss": self.must_not_miss,
            "medication_contributors": self.medication_contributors,
            "lifestyle_contributors": self.lifestyle_contributors,
            "missing_information": self.missing_information,
            "suggested_evaluation": self.suggested_evaluation,
            "uncertainty": self.uncertainty,
            "safe_scope": self.safe_scope,
        }


@dataclass
class AyurvedaReasoning:
    presenting_pattern: str = ""
    dosha_involvement: list[str] = field(default_factory=list)
    agni: str = ""
    ama: str = ""
    nidana: list[str] = field(default_factory=list)
    ahara_factors: list[str] = field(default_factory=list)
    vihara_factors: list[str] = field(default_factory=list)
    dushya: list[str] = field(default_factory=list)
    srotas: list[str] = field(default_factory=list)
    samprapti: str = ""
    vikriti: str = ""
    prakriti_status: str = "not assessed"
    prakriti: str = ""
    missing_information: list[str] = field(default_factory=list)
    traditional_management_concepts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Synthesis:
    agreement: list[str] = field(default_factory=list)
    difference: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    safety_conflicts: list[str] = field(default_factory=list)
    combined_scope: str = ""

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Reasoning:
    modern: ModernReasoning = field(default_factory=ModernReasoning)
    ayurveda: AyurvedaReasoning = field(default_factory=AyurvedaReasoning)
    synthesis: Synthesis = field(default_factory=Synthesis)
    ok: bool = True

    def as_dict(self) -> dict:
        return {"modern": self.modern.as_dict(),
                "ayurveda": self.ayurveda.as_dict(),
                "synthesis": self.synthesis.as_dict(),
                "ok": self.ok}

    def render(self) -> str:
        """The internal assessment, as a block for the composer.

        Deliberately compact and deliberately hedged in its own wording: the
        composer reads this and writes prose, and anything phrased as certainty
        here has a way of arriving as certainty on the screen.
        """
        parts = []
        likely = [p for p in self.modern.possible_explanations if p.likelihood != "unlikely"]
        if likely:
            parts.append(
                "MODERN VIEW (internal, never state any of these as a diagnosis): "
                + "; ".join(f"{p.name} — supported by {', '.join(p.supports[:2])}"
                            for p in likely[:3])
            )
        if self.modern.must_not_miss:
            parts.append(
                "WORTH RULING OUT: "
                + "; ".join(m.get("name", "") for m in self.modern.must_not_miss[:3])
            )
        if self.modern.lifestyle_contributors:
            parts.append(
                "LIFESTYLE CONTRIBUTORS: " + ", ".join(self.modern.lifestyle_contributors[:4])
            )
        ay = self.ayurveda
        if ay.presenting_pattern or ay.dosha_involvement:
            bits = [ay.presenting_pattern] if ay.presenting_pattern else []
            if ay.dosha_involvement:
                bits.append("dosha involvement: " + ", ".join(ay.dosha_involvement[:3]))
            if ay.agni:
                bits.append(f"agni: {ay.agni}")
            if ay.nidana:
                bits.append("nidana: " + ", ".join(ay.nidana[:3]))
            parts.append("AYURVEDA VIEW (a separate reading, not a translation of the "
                         "above): " + "; ".join(bits))
        if ay.prakriti_status != "assessed":
            parts.append(
                "PRAKRITI IS NOT ESTABLISHED. Do not name one, and do not imply "
                "one from this complaint."
            )
        if self.synthesis.safety_conflicts:
            parts.append(
                "SAFETY CONFLICT: " + "; ".join(self.synthesis.safety_conflicts[:2])
            )
        if self.synthesis.combined_scope:
            parts.append(f"APPROPRIATE SCOPE: {self.synthesis.combined_scope}")
        return "\n".join(parts)


def _possibilities(raw) -> list[Possibility]:
    out = []
    for item in (raw or [])[:5]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:80]
        if not name:
            continue
        out.append(Possibility(
            name=name,
            supports=[str(s)[:90] for s in (item.get("supports") or [])[:4] if str(s).strip()],
            against=[str(s)[:90] for s in (item.get("against") or [])[:4] if str(s).strip()],
            likelihood=str(item.get("likelihood") or "possible").lower(),
        ))
    return out


def _strings(raw, limit: int = 6, size: int = 100) -> list[str]:
    return [str(x).strip()[:size] for x in (raw or [])[:limit] if str(x).strip()]


def enforce(reasoning: Reasoning, *, history: str = "") -> Reasoning:
    """Apply the three rules that must hold whatever the model returned.

    Pure, so each rule is testable without a model — which matters, because
    these are the ones that do damage on the day the model is careless.
    """
    # 1. Prakriti is not guessable from a complaint.
    if not _PRAKRITI_EVIDENCE.search(history or ""):
        reasoning.ayurveda.prakriti = ""
        reasoning.ayurveda.prakriti_status = "not assessed"

    # 2. No possibility may be phrased as a certainty.
    for possibility in reasoning.modern.possible_explanations:
        possibility.name = _CERTAINTY.sub("", possibility.name).strip(" ,.-")
        if possibility.likelihood not in ("common", "possible", "unlikely"):
            possibility.likelihood = "possible"
    reasoning.modern.safe_scope = _CERTAINTY.sub("", reasoning.modern.safe_scope)

    # 3. An Ayurveda chain with nothing behind it is dropped. A samprapti
    #    needs at least a dosha and a nidana to be a chain rather than a
    #    sentence; dushya and srotas need the pattern to have been described.
    ay = reasoning.ayurveda
    if not (ay.dosha_involvement and ay.nidana):
        ay.samprapti = ""
    if not ay.presenting_pattern:
        ay.dushya = []
        ay.srotas = []
    return reasoning


def parse(raw: dict | None, *, history: str = "") -> Reasoning:
    """Turn the model's JSON into the three structures, then enforce the rules."""
    data = raw or {}
    modern_raw = data.get("modern") or {}
    ay_raw = data.get("ayurveda") or {}
    syn_raw = data.get("synthesis") or {}

    modern = ModernReasoning(
        possible_explanations=_possibilities(modern_raw.get("possible_explanations")),
        must_not_miss=[m for m in (modern_raw.get("must_not_miss") or [])[:4]
                       if isinstance(m, dict) and str(m.get("name") or "").strip()],
        medication_contributors=_strings(modern_raw.get("medication_contributors")),
        lifestyle_contributors=_strings(modern_raw.get("lifestyle_contributors")),
        missing_information=_strings(modern_raw.get("missing_information")),
        suggested_evaluation=_strings(modern_raw.get("suggested_evaluation")),
        uncertainty=str(modern_raw.get("uncertainty") or "moderate").lower(),
        safe_scope=str(modern_raw.get("safe_scope") or "")[:240],
    )
    ayurveda = AyurvedaReasoning(
        presenting_pattern=str(ay_raw.get("presenting_pattern") or "")[:160],
        dosha_involvement=_strings(ay_raw.get("dosha_involvement"), 4, 40),
        agni=str(ay_raw.get("agni") or "")[:120],
        ama=str(ay_raw.get("ama") or "")[:120],
        nidana=_strings(ay_raw.get("nidana")),
        ahara_factors=_strings(ay_raw.get("ahara_factors")),
        vihara_factors=_strings(ay_raw.get("vihara_factors")),
        dushya=_strings(ay_raw.get("dushya"), 4, 40),
        srotas=_strings(ay_raw.get("srotas"), 4, 40),
        samprapti=str(ay_raw.get("samprapti") or "")[:240],
        vikriti=str(ay_raw.get("vikriti") or "")[:120],
        prakriti_status=str(ay_raw.get("prakriti_status") or "not assessed")[:40],
        prakriti=str(ay_raw.get("prakriti") or "")[:60],
        missing_information=_strings(ay_raw.get("missing_information")),
        traditional_management_concepts=_strings(
            ay_raw.get("traditional_management_concepts")
        ),
    )
    synthesis = Synthesis(
        agreement=_strings(syn_raw.get("agreement")),
        difference=_strings(syn_raw.get("difference")),
        unresolved=_strings(syn_raw.get("unresolved")),
        safety_conflicts=_strings(syn_raw.get("safety_conflicts")),
        combined_scope=str(syn_raw.get("combined_scope") or "")[:240],
    )
    return enforce(Reasoning(modern=modern, ayurveda=ayurveda, synthesis=synthesis),
                   history=history)


def _reason_sync(history: str, profile: str, episode: str, guide: str, triage: str) -> dict:
    raw = llm_invoke(
        [__import__("langchain_core.messages", fromlist=["HumanMessage"]).HumanMessage(
            content=prompts.CLINICAL_REASONING_PROMPT.format(
                history=history or "(nothing yet)",
                profile=profile or "(nothing known about them yet)",
                episode=episode or "(no episode detail yet)",
                guide=guide or "(no specific guide for this complaint)",
                triage=triage or "GREEN",
            )
        )],
        temperature=REASONING_TEMPERATURE,
        json_mode=True,
        max_tokens=config.MAX_TOKENS_PLANNER,
    )
    return extract_json(raw) or {}


async def reason(
    *,
    history: str = "",
    profile: str = "",
    episode: str = "",
    guide: str = "",
    triage: str = "GREEN",
) -> Reasoning:
    """Both views plus the synthesis, in one call.

    FAILS EMPTY, NOT WRONG. An unreachable model returns a `Reasoning` with
    `ok=False` and nothing in it, so the composer simply has less to work with
    — it never receives a half-parsed assessment it might state as fact.
    """
    try:
        raw = await asyncio.to_thread(_reason_sync, history, profile, episode, guide, triage)
    except Exception as error:  # noqa: BLE001
        print(f"[clinical] reasoning failed: {error}")
        return Reasoning(ok=False)
    parsed = parse(raw, history=history)
    parsed.ok = bool(raw)
    return parsed
