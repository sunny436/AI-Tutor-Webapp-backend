"""requirements.lock (what production and CI install, with hashes) must satisfy requirements.txt.

Editing requirements.txt without regenerating the lock (`bun run lock:backend`) fails here, so a
release can never ship dependencies other than the ones CI installed and tested.
"""

import re
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

BACKEND = Path(__file__).resolve().parents[1]


def locked_versions() -> dict[str, str]:
    pins = re.findall(
        r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", (BACKEND / "requirements.lock").read_text(encoding="utf-8"), re.M
    )
    return {canonicalize_name(name): version for name, version in pins}


def test_every_requirement_is_locked_at_an_allowed_version():
    locked = locked_versions()
    for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        name = canonicalize_name(requirement.name)
        assert name in locked, f"{requirement.name} is not in requirements.lock: run `bun run lock:backend`"
        assert requirement.specifier.contains(locked[name], prereleases=True), (
            f"requirements.lock pins {requirement.name}=={locked[name]}, outside {requirement.specifier}"
        )


def test_every_locked_package_has_hashes():
    text = (BACKEND / "requirements.lock").read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", text)
    pinned = [block for block in blocks if re.match(r"[A-Za-z0-9_.-]+==", block)]
    assert pinned and all("--hash=sha256:" in block for block in pinned)
