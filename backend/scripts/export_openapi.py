"""Write (or check) the committed API contract at ../docs/openapi.json.

    python scripts/export_openapi.py          # regenerate
    python scripts/export_openapi.py --check  # exit 1 if the committed file is stale

The frontend repository consumes this file; a test fails when it drifts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TARGET = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def build_openapi() -> dict:
    from app.llm.fake import FakeProvider
    from app.main import create_app
    from app.settings import Settings

    settings = Settings(_env_file=None, app_env="development", llm_provider="fake", email_backend="memory")
    return create_app(settings, llm=FakeProvider()).openapi()


def main() -> int:
    spec = build_openapi()
    rendered = json.dumps(spec, indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if json.loads(current or "{}") != spec:
            print(f"{TARGET} is stale. Run: python scripts/export_openapi.py")
            return 1
        print("openapi.json is current")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered, encoding="utf-8", newline="\n")  # LF on every OS, like the repository
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
