"""
Cross-provider model naming. Deterministic — no network, no keys.

    python tests/test_provider_split.py

Guards `llm.split_provider`, which is what lets one MODEL_CHAIN span Groq and
OpenRouter. That matters because Groq meters tokens-per-day PER MODEL: once its
two capable models are spent the assistant is down for the day, and only a
second provider is genuinely separate capacity.

The case worth having a test for is OpenRouter's ids, which contain colons of
their own — `nvidia/nemotron-3-nano-30b-a3b:free`. A naive `split(":")` turns
that into provider "nvidia" and a truncated model, so every free OpenRouter model
would silently resolve to the wrong thing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from src.llm import split_provider  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


def expect(entry: str, provider: str, model: str) -> None:
    got_provider, got_model = split_provider(entry)
    ok = got_provider == provider and got_model == model
    check(f"{entry!r} -> ({provider}, {model})", ok, f"got ({got_provider}, {got_model})")


# --- explicit provider prefixes --------------------------------------------
expect("groq:llama-3.3-70b-versatile", "groq", "llama-3.3-70b-versatile")
expect("groq:openai/gpt-oss-120b", "groq", "openai/gpt-oss-120b")
expect("ollama:llama3.2", "ollama", "llama3.2")
expect("ollima:deepseek-v4-flash", "ollima", "deepseek-v4-flash")
# Ollima ids can carry colons of their own, the same trap as OpenRouter.
expect(
    "ollima:tensorzero::model_name::glm-4.7",
    "ollima",
    "tensorzero::model_name::glm-4.7",
)
# "ollima" and "ollama" differ by one letter and are different providers -
# one is a hosted OpenAI-compatible gateway, the other the local runtime.
expect("ollima:x", "ollima", "x")
expect("ollama:x", "ollama", "x")

# --- THE case that motivated this: colons inside an OpenRouter id -----------
expect(
    "openrouter:nvidia/nemotron-3-nano-30b-a3b:free",
    "openrouter",
    "nvidia/nemotron-3-nano-30b-a3b:free",
)
expect(
    "openrouter:google/gemma-4-26b-a4b-it:free",
    "openrouter",
    "google/gemma-4-26b-a4b-it:free",
)

# --- unprefixed names must behave exactly as before ------------------------
expect("llama-3.3-70b-versatile", config.LLM_PROVIDER, "llama-3.3-70b-versatile")
expect("openai/gpt-oss-120b", config.LLM_PROVIDER, "openai/gpt-oss-120b")

# A bare model id that merely CONTAINS a colon must not be mistaken for a
# provider prefix — "nvidia" is not a provider we know.
expect(
    "nvidia/nemotron-3-nano-30b-a3b:free",
    config.LLM_PROVIDER,
    "nvidia/nemotron-3-nano-30b-a3b:free",
)

# --- degenerate input must not raise ---------------------------------------
for entry in ("", "groq:", ":free", "groq"):
    try:
        provider, model = split_provider(entry)
        check(f"{entry!r} handled without raising", True, f"({provider}, {model})")
    except Exception as error:  # noqa: BLE001
        check(f"{entry!r} handled without raising", False, str(error))

# --- the configured chain must resolve to real providers -------------------
for entry in (m.strip() for m in config.MODEL_CHAIN.split(",")):
    if not entry:
        continue
    provider, model = split_provider(entry)
    check(
        f"chain entry {entry!r} resolves to a known provider",
        provider in ("groq", "openrouter", "ollima", "ollama") and bool(model),
        f"({provider}, {model})",
    )

passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== provider split: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
sys.exit(0 if passed == len(results) else 1)
