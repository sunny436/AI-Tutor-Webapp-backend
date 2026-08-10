"""
Cooldown duration after a model reports being out of quota. No network.

    python tests/test_cooldown.py

The bug this guards: a flat 900s cooldown froze a model for fifteen minutes even
when the provider itself said it would be usable again in four. Groq's
tokens-per-day bucket refills continuously, so during those extra eleven minutes
the chain fell through to providers that were genuinely dead and the user saw
"AI service unavailable" while a working model sat idle in cooldown.

The failure was invisible from outside the process: a direct API probe succeeded
(no cooldown state) while the running server refused, which reads like a code
bug rather than a stale timer.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.llm import COOLDOWN_SECONDS, _RETRY_AFTER, _classify  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


def cooldown_for(detail: str) -> float:
    """Mirror of the policy in `invoke`, so the arithmetic is asserted directly."""
    match = _RETRY_AFTER.search(detail)
    stated = (
        int(match.group(1) or 0) * 60 + float(match.group(2))
        if match
        else COOLDOWN_SECONDS
    )
    return min(max(stated, 30.0), COOLDOWN_SECONDS)


# The real Groq message that caused the outage.
GROQ_TPD = (
    "Error code: 429 - Rate limit reached for model `llama-3.3-70b-versatile` in "
    "organization `org_x` service tier `on_demand` on tokens per day (TPD): "
    "Limit 100000, Used 99338, Requested 1644. Please try again in 4m32.16s."
)

check("Groq TPD message is classified as exhausted", _classify(GROQ_TPD) == "exhausted")

wait = cooldown_for(GROQ_TPD)
check(
    "cooldown honours the provider's stated 4m32s",
    abs(wait - 272.16) < 1.0,
    f"{wait:.1f}s",
)
check(
    "and is far below the old flat 900s freeze",
    wait < COOLDOWN_SECONDS,
    f"{wait:.0f}s vs {COOLDOWN_SECONDS:.0f}s",
)

# Seconds-only form.
wait = cooldown_for("quota exceeded. Please try again in 45.5s")
check("seconds-only retry figure is parsed", abs(wait - 45.5) < 0.5, f"{wait:.1f}s")

# A very short figure must still be floored, or an exhausted model gets hammered.
wait = cooldown_for("quota exceeded. Please try again in 2.0s")
check("a tiny figure is floored at 30s", wait == 30.0, f"{wait:.1f}s")

# No figure at all -> the 900s backstop.
wait = cooldown_for("insufficient_quota for this account")
check(
    "no stated figure falls back to the 900s backstop",
    wait == COOLDOWN_SECONDS,
    f"{wait:.0f}s",
)

# A stated figure longer than the backstop must not exceed it.
wait = cooldown_for("quota exceeded. Please try again in 60m0.0s")
check(
    "a figure longer than the backstop is capped",
    wait == COOLDOWN_SECONDS,
    f"{wait:.0f}s",
)

# Per-minute limits must stay TRANSIENT — they are waited out, never cooled down.
check(
    "a per-minute limit is transient, not exhausted",
    _classify("Rate limit reached ... on tokens per minute (TPM). try again in 1.2s")
    == "transient",
)

# OpenRouter's daily cap states no retry time, so it takes the backstop.
OPENROUTER = (
    "Error code: 429 - Rate limit exceeded: free-models-per-day. "
    "Add 10 credits to unlock 1000 free model requests per day"
)
check(
    "OpenRouter free-per-day is classified as exhausted",
    _classify(OPENROUTER) == "exhausted",
    _classify(OPENROUTER),
)

passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== cooldown: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
sys.exit(0 if passed == len(results) else 1)
