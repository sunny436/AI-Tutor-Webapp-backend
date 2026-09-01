"""
The chain has to come back on its own. A restart is not a recovery strategy.

WHAT THIS PINS
An upstream blip put the primary into cooldown; the only other chain entry was
structurally broken (`unknown provider for model`, wrapped in a 502). Every
request then failed with "AI service unavailable" — and kept failing, because
a cooling model was omitted from the candidate list entirely, so the primary
was never tried again. Restarting the server fixed it instantly, which is the
proof: a restart does nothing but clear `_cooldown`.

Four properties, and the fourth is the one that removes the restart:

  1. a failing primary hands over to the fallback rather than erroring;
  2. the fallback actually answers;
  3. when the fallback ALSO fails, a cooling primary is probed, not skipped;
  4. one successful probe clears the cooldown, so the very next call is back
     on the primary with no operator action.

DETERMINISTIC. No network, no sleeping on real clocks: `get_llm` is replaced
with scripted clients and `time.sleep` is captured, so a "rate limited, waiting
6s" path costs nothing and the wait itself can be asserted on.

    python tests/test_llm_recovery.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from src import llm  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


PRIMARY = "ollima:gemini-3.1-flash-lite"
FALLBACK = "ollima:gemini-3.5-flash-low"

# The real strings, verbatim from the live outage.
QUOTA = "Error code: 429 - rate limit reached for tokens per day (TPD)"
NOT_SERVED = (
    "Error code: 502 - {'error': {'message': 'All variants failed with errors: "
    "gemini-3.5-flash-low: All model providers failed to infer with errors: "
    "sidecar: Error 400 Bad Request from openai client: {\"error\":{\"message\":"
    "\"unknown provider for model gemini-3.5-flash-low\",\"type\":"
    "\"invalid_request_error\",\"code\":\"model_not_found\"}}'}}"
)

CALLS: list[str] = []
SLEPT: list[float] = []


class _Reply:
    def __init__(self, text: str) -> None:
        self.content = text


class _Client:
    """A model that answers, or raises whatever `behaviour` currently says."""

    def __init__(self, name: str) -> None:
        self.name = name

    def invoke(self, messages):
        CALLS.append(self.name)
        problem = BEHAVIOUR.get(self.name)
        if problem:
            raise RuntimeError(problem)
        return _Reply(f"answer from {self.name}")


BEHAVIOUR: dict[str, str] = {}


def _fake_get_llm(temperature=0.4, json_mode=False, model="", max_tokens=0):
    return _Client(model or PRIMARY)


def _fake_sleep(seconds: float) -> None:
    SLEPT.append(seconds)


def reset(behaviour: dict[str, str] | None = None) -> None:
    CALLS.clear()
    SLEPT.clear()
    llm._cooldown.clear()
    BEHAVIOUR.clear()
    BEHAVIOUR.update(behaviour or {})


llm.get_llm = _fake_get_llm
llm.time.sleep = _fake_sleep
llm.MODEL_CHAIN = [PRIMARY, FALLBACK]


# ===========================================================================
# 1-2. THE PRIMARY FAILS AND THE FALLBACK IS USED
# ===========================================================================
reset({PRIMARY: QUOTA})
answer = llm.invoke([{"role": "user", "content": "hi"}])
check("1. a primary out of quota does not raise", bool(answer), answer)
check("2. THE FALLBACK ANSWERS", answer == f"answer from {FALLBACK}", answer)
check("3. the primary was tried first", CALLS[0] == PRIMARY, CALLS)
check("4. the primary is now cooling down", PRIMARY in llm._cooldown, list(llm._cooldown))
check("5. the fallback is not cooling down", FALLBACK not in llm._cooldown)


# ===========================================================================
# 3. THE FALLBACK IS STRUCTURALLY BROKEN TOO — the exact live outage
# ===========================================================================
reset({PRIMARY: QUOTA, FALLBACK: NOT_SERVED})
try:
    llm.invoke([{"role": "user", "content": "hi"}])
    outage_raised = False
except Exception:
    outage_raised = True
check("6. with BOTH models down the caller is told, not left hanging", outage_raised)
check("7. ...and both were actually tried", set(CALLS) == {PRIMARY, FALLBACK}, CALLS)
check("8. A MODEL THE PROVIDER DOES NOT SERVE IS NOT SLEPT ON",
      SLEPT == [], SLEPT)
check("9. ...and it is cooled down rather than left ranked as healthy",
      FALLBACK in llm._cooldown, list(llm._cooldown))
check("10. one attempt each — no retry ladder on a structural failure",
      CALLS.count(FALLBACK) == 1, CALLS)


# ===========================================================================
# 4. THE PRIMARY RECOVERS — and the process finds out by itself
#
# This is the case that used to need a restart. Both models are cooling down,
# the fallback is still broken, and the primary has quietly come back. Nothing
# resets anything; the next ordinary request has to discover it.
# ===========================================================================
reset({PRIMARY: QUOTA, FALLBACK: NOT_SERVED})
try:
    llm.invoke([{"role": "user", "content": "hi"}])
except Exception:
    pass
check("11. both models are cooling down after the outage",
      PRIMARY in llm._cooldown and FALLBACK in llm._cooldown, list(llm._cooldown))

cooldown_before = llm._cooldown.get(PRIMARY, 0.0)
BEHAVIOUR.pop(PRIMARY)          # the provider comes back. Nothing tells us.
CALLS.clear()
SLEPT.clear()

recovered = llm.invoke([{"role": "user", "content": "hi"}])
check("12. THE RECOVERED PRIMARY IS PROBED, NOT SKIPPED", PRIMARY in CALLS, CALLS)
check("13. ...and it answers", recovered == f"answer from {PRIMARY}", recovered)
check("14. NO 'AI service unavailable' AFTER RECOVERY — nothing raised", True)
check("15. its cooldown is cleared by the successful probe",
      PRIMARY not in llm._cooldown, list(llm._cooldown))
check("16. the cooldown really had been in force (the probe was not free)",
      cooldown_before > time.monotonic(), f"{cooldown_before:.1f}")

# ...and the NEXT call is straight back on the primary, first try, with the
# broken fallback never touched. This is "the process returned to normal".
CALLS.clear()
again = llm.invoke([{"role": "user", "content": "hi"}])
check("17. THE VERY NEXT CALL GOES TO THE PRIMARY FIRST", CALLS[0] == PRIMARY, CALLS)
check("18. ...and the broken fallback is never reached", FALLBACK not in CALLS, CALLS)
check("19. ...with no restart, no manual step, no cleared state",
      again == f"answer from {PRIMARY}", again)


# ===========================================================================
# 5. THE ROUTER'S PINNED MODEL RECOVERS THE SAME WAY
#
# The router pins its model, and the pinned path had its own copy of the
# "drop the cooling model" bug (`return others or [pinned]`).
# ===========================================================================
reset({PRIMARY: QUOTA, FALLBACK: NOT_SERVED})
try:
    llm.invoke([{"role": "user", "content": "hi"}], model=PRIMARY)
except Exception:
    pass
BEHAVIOUR.pop(PRIMARY)
CALLS.clear()
pinned_answer = llm.invoke([{"role": "user", "content": "hi"}], model=PRIMARY)
check("20. a pinned model in cooldown is still probed when nothing else works",
      pinned_answer == f"answer from {PRIMARY}", pinned_answer)
check("21. ...and the pin is honoured again once it is healthy",
      llm._available_models(PRIMARY)[0] == PRIMARY, llm._available_models(PRIMARY))


# ===========================================================================
# 6. THE COOLDOWN STILL DOES ITS JOB
#
# The point of demoting rather than dropping is that a cooling model costs one
# probe at the END, not a doomed first attempt on every turn. If a healthy
# model can answer, the cooling one must never be reached at all.
# ===========================================================================
reset({PRIMARY: QUOTA})
llm.invoke([{"role": "user", "content": "hi"}])       # primary -> cooldown
CALLS.clear()
llm.invoke([{"role": "user", "content": "hi"}])
check("22. a cooling model is NOT tried while a healthy one answers",
      CALLS == [FALLBACK], CALLS)
check("23. ...so the cooldown still saves the doomed request it exists to save",
      PRIMARY not in CALLS, CALLS)

# Ordering: healthy first, cooling last, every model present exactly once.
reset({})
llm._cooldown[PRIMARY] = time.monotonic() + 600
order = llm._available_models("")
check("24. a cooling model is demoted to last, never dropped",
      order == [FALLBACK, PRIMARY], order)
check("25. every chain entry appears exactly once",
      sorted(order) == sorted({PRIMARY, FALLBACK}), order)


# ===========================================================================
# 7. A GENUINELY FATAL ERROR STILL STOPS EVERYTHING
#
# Widening the classifier must not turn a bad API key into 900 seconds of
# hopeful retrying across every model.
# ===========================================================================
reset({PRIMARY: "401 invalid api key", FALLBACK: "401 invalid api key"})
try:
    llm.invoke([{"role": "user", "content": "hi"}])
    fatal_raised = False
except Exception:
    fatal_raised = True
check("26. a bad key still raises immediately", fatal_raised)
check("27. ...on the first model, without walking the chain",
      CALLS == [PRIMARY], CALLS)
check("28. ...and does not cool anything down",
      llm._cooldown == {}, list(llm._cooldown))

# A transient rate limit still gets the full retry ladder.
reset({PRIMARY: "429 rate limited", FALLBACK: None or ""})
llm.invoke([{"role": "user", "content": "hi"}])
check("29. a transient limit still retries before moving on",
      CALLS.count(PRIMARY) == llm.MAX_ATTEMPTS, CALLS)
check("30. ...and does sleep between attempts", len(SLEPT) > 0, SLEPT)


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== llm recovery: {passed}/{len(results)} passed =====")
if passed != len(results):
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name} :: {detail}")
    sys.exit(1)
