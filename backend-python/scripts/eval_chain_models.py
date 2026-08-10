"""
scripts/eval_chain_models.py
----------------------------
Score candidate models on THIS project's two hot paths, so MODEL_CHAIN is
ordered by measurement rather than by parameter count.

Provider-agnostic: entries may carry a `groq:` / `openrouter:` / `ollama:`
prefix, exactly as MODEL_CHAIN does, so a candidate is measured through the same
code path that will serve it in production.

    .venv\\Scripts\\python.exe scripts\\eval_chain_models.py
    .venv\\Scripts\\python.exe scripts\\eval_chain_models.py --models openrouter:nvidia/nemotron-3-nano-30b-a3b:free

WHY THIS EXISTS
Groq meters tokens-per-day PER MODEL, so the chain is what keeps the assistant
alive once the primary runs dry — but a fallback is only useful if it can
actually do the job. A model that cannot emit JSON under the router's token cap
silently turns every health complaint into small talk (measured: that is exactly
what llama-3.1-8b-instant does), and the user sees a chatty non-answer rather
than an error.

WHAT IS MEASURED — the two calls that decide whether a consultation happens:

  ROUTER   Must return valid JSON under MAX_TOKENS_ROUTER and classify a plain
           health complaint as "health". Getting this wrong costs the entire
           feature.
  PLANNER  Must return >= 4 usable intake questions in the user's language.
           Three vague questions is the difference between a consultation and a
           shrug.

Each model is judged only against itself and this prompt set. No cross-model
score comparison, and no claim beyond what was run.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402
from src import prompts  # noqa: E402
from src.consult.repair import extract_json, parse_plan  # noqa: E402
from src.llm import _build  # noqa: E402

# Chat-capable, long-context, general-purpose. Excludes whisper (audio),
# orpheus (speech), prompt-guard (classifier) and allam-2-7b (Arabic).
CANDIDATES = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "llama-3.1-8b-instant",
    "groq/compound-mini",
]

ROUTER_PROBE = "mujhe khane ke baad acidity aur gas hoti hai"
PLANNER_PROBE = "acidity aur gas khane ke baad"


def score(model: str) -> dict:
    out = {"model": model, "router": "-", "intent": "-", "plan_q": "-", "secs": 0.0, "error": ""}
    started = time.monotonic()

    # --- router: JSON under the cap, correct intent -------------------------
    try:
        prompt = prompts.ROUTER_PROMPT.format(
            message=ROUTER_PROBE, history="", greeted="no"
        )
        client = _build(model, 0.7, True, config.MAX_TOKENS_ROUTER)
        raw = str(client.invoke([HumanMessage(content=prompt)]).content)
        parsed = extract_json(raw) or {}
        out["router"] = "ok" if parsed else "BAD JSON"
        out["intent"] = parsed.get("intent", "?")
    except Exception as error:  # noqa: BLE001
        out["router"] = "ERROR"
        out["error"] = str(error)[:90]
        out["secs"] = round(time.monotonic() - started, 1)
        return out

    # --- planner: enough usable questions -----------------------------------
    try:
        prompt = prompts.INTAKE_PLAN_PROMPT.format(
            problem=PLANNER_PROBE, collected="(nothing yet)", language="hinglish"
        )
        client = _build(model, 0.4, True, config.MAX_TOKENS_PLANNER)
        raw = str(client.invoke([HumanMessage(content=prompt)]).content)
        out["plan_q"] = len(parse_plan(raw).questions)
    except Exception as error:  # noqa: BLE001
        out["plan_q"] = "ERROR"
        out["error"] = str(error)[:90]

    out["secs"] = round(time.monotonic() - started, 1)
    return out


if "--models" in sys.argv:
    CANDIDATES = [
        m.strip() for m in sys.argv[sys.argv.index("--models") + 1].split(",") if m.strip()
    ]

print(f"{'model':<52} {'router':<9} {'intent':<9} {'plan_q':<7} {'secs':<6} note")
print("-" * 110)
rows = []
for name in CANDIDATES:
    row = score(name)
    rows.append(row)
    print(
        f"{row['model']:<52} {str(row['router']):<9} {str(row['intent']):<9} "
        f"{str(row['plan_q']):<7} {str(row['secs']):<6} {row['error']}"
    )

print("\nUsable = router JSON ok AND intent 'health' AND plan_q >= 4:")
for row in rows:
    ok = (
        row["router"] == "ok"
        and row["intent"] == "health"
        and isinstance(row["plan_q"], int)
        and row["plan_q"] >= 4
    )
    print(f"  {'YES' if ok else 'no ':<4} {row['model']}")
