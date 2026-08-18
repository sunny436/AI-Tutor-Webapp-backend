"""
The exported wire contract must not fall behind the models.

    python tests/test_contract.py

Half of the drift guard. This side proves `docs/consult-contract.json` still
describes what `src/consult/schema.py` actually promises; `contract.test.ts` on the
frontend proves the TypeScript still matches that file. Neither repository can move
the contract on its own without a red test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from scripts.export_contract import build  # noqa: E402

CONTRACT = ROOT.parent / "docs" / "consult-contract.json"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


check("the exported contract exists", CONTRACT.exists(), str(CONTRACT))

if CONTRACT.exists():
    committed = CONTRACT.read_text(encoding="utf-8")
    rebuilt = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    check(
        "the exported contract still matches the models",
        committed == rebuilt,
        "" if committed == rebuilt else "stale - run: python scripts/export_contract.py",
    )

    data = json.loads(committed)

    # The values the frontend branches on. Losing one silently breaks a code path
    # rather than failing a build.
    check("kind values are published", set(data["enums"]["kind"]) >= {"chat", "answer", "escalation", "error"})
    check("gathering is a published phase", "gathering" in data["enums"]["phase"])
    check(
        "the retired card phases are still accepted",
        {"collecting", "choosing"} <= set(data["enums"]["phase"]),
        "removing them resets every conversation persisted before P4",
    )
    check(
        "CONSULTING lists the phases where a typed message continues a consultation",
        "gathering" in data["phase_groups"]["consulting"],
    )
    check(
        "every source namespace the UI groups on is published",
        set(data["source_namespaces"]) == {"knowledge", "report", "graphrag", "memory"},
        str(data["source_namespaces"]),
    )
    check(
        "the request fields the frontend sends are published",
        {"problem", "freeText", "context", "conversationId", "bot_id"} <= set(data["request_fields"]),
    )
    # `symptoms` feeds the vector query; a frontend that drops it degrades retrieval
    # quietly rather than visibly.
    check("ConsultContext publishes symptoms", "symptoms" in data["models"]["ConsultContext"])
    check("ConsultResult publishes sources", "sources" in data["models"]["ConsultResult"])

passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== contract: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
sys.exit(0 if passed == len(results) else 1)
