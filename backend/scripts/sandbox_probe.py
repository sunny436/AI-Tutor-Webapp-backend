"""Check the file extractor sandbox on this host, with the exact properties production uses.

    cd /opt/aichat/app/backend && .venv/bin/python scripts/sandbox_probe.py      (as root, on the VM)

Runs the real runner (app/files/processing.py) on a two-page text PDF and on an image that
needs OCR, then runs a small script inside the same sandbox that must NOT be able to read the
secrets or reach the network. Prints PASS/FAIL lines only (never file contents); exits 1 on any
failure. Changes nothing: the units are transient and collected.
"""

from __future__ import annotations

import asyncio
import io
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.files.processing import BACKEND_DIR, SANDBOX_PROPERTIES, run_extractor  # noqa: E402

FIXTURE = BACKEND_DIR / "tests" / "fixtures" / "two-pages.pdf"
results: list[bool] = []


def check(name: str, ok: bool, note: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f'  ({note})' if note else ''}")


def ocr_image() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (1600, 400), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=72)
    draw.text((40, 60), "Photosynthesis happens", fill=0, font=font)
    draw.text((40, 200), "in the leaves of plants", fill=0, font=font)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


async def pieces(data: bytes):
    for start in range(0, len(data), 1024 * 1024):
        yield data[start : start + 1024 * 1024]


async def extraction_checks() -> None:
    result = await run_extractor("systemd", "aichat-extract-probe-pdf.service", "pdf", pieces(FIXTURE.read_bytes()))
    check("pdf in the sandbox: two pages", result.code is None and len(result.pages) == 2, result.code or "")
    result = await run_extractor("systemd", "aichat-extract-probe-png.service", "image", pieces(ocr_image()))
    text = " ".join(page["text"] for page in result.pages).lower()
    check(
        "image OCR in the sandbox (Tesseract eng+hin)",
        result.code is None and "photosynthesis" in text,
        result.code or "",
    )


ESCAPE = """
import os, socket
def denied(path):
    try:
        os.listdir(path) if os.path.isdir(path) else open(path, 'rb').read(1)
        return False
    except OSError:
        return True
checks = {
    "secrets": denied("/etc/aichat/api.env"),
    "tunnel": denied("/etc/cloudflared"),
    "backups": denied("/var/backups/aichat"),
    "docker": denied("/var/lib/docker"),
}
try:
    socket.create_connection(("1.1.1.1", 443), timeout=3)
    checks["network"] = False
except OSError:
    checks["network"] = True
checks["no secrets in env"] = not any(k.endswith(("_KEY", "_TOKEN", "_PASSWORD")) for k in os.environ)
print(",".join(f"{k}={'ok' if v else 'LEAK'}" for k, v in checks.items()))
"""


def isolation_checks() -> None:
    properties = [arg for prop in SANDBOX_PROPERTIES for arg in ("-p", prop)]
    output = subprocess.run(
        [
            "systemd-run",
            "--quiet",
            "--pipe",
            "--wait",
            "--collect",
            "--unit=aichat-extract-probe-escape.service",
            *properties,
            sys.executable,
            "-c",
            ESCAPE,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    ).stdout.strip()
    for item in output.split(","):
        name, _, verdict = item.partition("=")
        check(f"sandbox blocks {name}", verdict == "ok")
    if not output:
        check("sandbox isolation script ran", False)


async def main() -> int:
    await extraction_checks()
    isolation_checks()
    print(f"==== {sum(results)}/{len(results)} passed ====")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
