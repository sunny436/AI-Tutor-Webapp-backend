"""
scripts/verify_free_only.py
---------------------------
Proof that every model this app can reach costs nothing.

    python scripts/verify_free_only.py

Reads the models the app is ACTUALLY configured to use out of `config`, then
looks each one up in OpenRouter's live catalogue and asserts its per-token price
is zero. Reading the config rather than a hardcoded list is the point: it cannot
drift out of date, and a paid model added later fails this immediately.

Exit code 1 if anything is billable.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

import config


def price(model: dict) -> tuple[float, float]:
    p = model.get("pricing", {}) or {}
    try:
        return float(p.get("prompt", 0)), float(p.get("completion", 0))
    except (TypeError, ValueError):
        return -1.0, -1.0


def main() -> int:
    catalogue = {
        m["id"]: m
        for m in httpx.get("https://openrouter.ai/api/v1/models", timeout=90).json()["data"]
    }

    in_use: list[tuple[str, str]] = [
        ("responder (PRIMARY_MODEL)", config.PRIMARY_MODEL),
        ("router   (ROUTER_MODEL)", config.ROUTER_MODEL),
    ]
    for i, name in enumerate(m.strip() for m in config.MODEL_CHAIN.split(",") if m.strip()):
        in_use.append((f"chain[{i}] (MODEL_CHAIN)", name))
    for i, name in enumerate(m.strip() for m in config.STT_MODEL_CHAIN.split(",") if m.strip()):
        in_use.append((f"speech-to-text[{i}]", name))
    if config.TTS_MODEL:
        in_use.append(("text-to-speech (TTS_MODEL)", config.TTS_MODEL))

    print(f"{'role':<30} {'model':<50} {'$/M in':>9} {'$/M out':>9}  verdict")
    print("-" * 112)

    billable = []
    seen = set()
    for role, name in in_use:
        model = catalogue.get(name)
        if model is None:
            print(f"{role:<30} {name:<50} {'?':>9} {'?':>9}  NOT IN CATALOGUE")
            billable.append((role, name))
            continue
        prompt, completion = price(model)
        free = prompt == 0 and completion == 0
        if not free:
            billable.append((role, name))
        print(
            f"{role:<30} {name:<50} "
            f"{prompt * 1_000_000:>9.2f} {completion * 1_000_000:>9.2f}  "
            f"{'FREE' if free else 'PAID'}"
        )
        seen.add(name)

    print("-" * 112)
    print(f"distinct models reachable: {len(seen)}")

    print("\nlocal, no API involved:")
    print(f"  embeddings  {config.EMBEDDING_MODEL}  (sentence-transformers, on this machine)")

    if not config.TTS_MODEL:
        print("\ntext-to-speech: browser speechSynthesis (Web Speech API)")
        print("  No free model on OpenRouter emits speech - of 400 models, four output")
        print("  audio: two are paid (openai/gpt-audio, gpt-audio-mini) and two generate")
        print("  music (google/lyria-*). So the Listen button uses the browser's own")
        print("  engine instead: free, no key, offline, and no round trip. A system")
        print("  voice rather than a neural one - set TTS_MODEL to trade money for")
        print("  quality; the button prefers the backend whenever it answers.")

    if billable:
        print("\nBILLABLE MODELS STILL CONFIGURED:")
        for role, name in billable:
            print(f"  {role}: {name}")
        return 1

    print("\nOK - every configured model costs $0 per token.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
