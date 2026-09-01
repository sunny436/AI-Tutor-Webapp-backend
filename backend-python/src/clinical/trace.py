"""
clinical/trace.py
-----------------
What happened this turn, in a form a person can read afterwards.

WHY
Today the only record of a decision is a scattering of `print("[consult] ...")`
lines interleaved with every other request on the box. That is enough to debug
a bug you already know about and useless for the questions that matter: why did
this person get this recommendation, what did it rest on, and what was blocked.
The spec asks for exactly that, for medical review, hallucination-hunting and
regression testing.

NEVER SHOWN TO THE USER. `PERSONA_CORE` rule 14 forbids naming the machinery,
and a confidence score on screen is the machinery. This is written to the log
and can be attached to a stored turn; it is not part of `ConsultResult.answer`.

CHEAP AND OPTIONAL. Building a trace must never be able to fail a turn, so
every method swallows its own errors: a broken audit line is not worth a 500 to
somebody asking about their acidity.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field


@dataclass
class Trace:
    """One turn's decisions. Append-only; `record` is the only way in."""

    conversation_id: str = ""
    started_at: float = field(default_factory=time.time)
    steps: list[dict] = field(default_factory=list)

    def record(self, stage: str, **detail) -> "Trace":
        try:
            self.steps.append({"stage": stage, **_plain(detail)})
        except Exception:  # noqa: BLE001 - an audit line must never fail a turn
            pass
        return self

    # --- the stages, named so a reader does not have to guess the keys ----
    def route(self, intent: str, **kw): return self.record("route", intent=intent, **kw)
    def patient_state(self, **kw): return self.record("patient_state", **kw)
    def episode(self, **kw): return self.record("episode", **kw)
    def triage(self, verdict): return self.record("triage", **_plain(verdict))
    def decision(self, verdict): return self.record("decision", **_plain(verdict))
    def retrieval(self, **kw): return self.record("retrieval", **kw)
    def evidence(self, **kw): return self.record("evidence", **kw)
    def gate(self, verdict): return self.record("gate", **_plain(verdict))
    def response(self, **kw): return self.record("response", **kw)

    def as_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "elapsed_s": round(time.time() - self.started_at, 2),
            "steps": self.steps,
        }

    def summary(self) -> str:
        """One line per stage, for a log that a human will actually scan."""
        parts = []
        for step in self.steps:
            stage = step.get("stage", "?")
            rest = {k: v for k, v in step.items() if k != "stage"}
            parts.append(f"{stage}={_short(rest)}")
        return " | ".join(parts)

    def emit(self) -> None:
        try:
            print(f"[trace] {self.summary()}")
        except Exception:  # noqa: BLE001
            pass


def _plain(value):
    """Anything -> something json can hold, without exploding on a dataclass."""
    if hasattr(value, "as_dict"):
        return _plain(value.as_dict())
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _short(value, limit: int = 90) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"
