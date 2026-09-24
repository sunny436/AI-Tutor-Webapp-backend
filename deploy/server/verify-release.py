#!/usr/bin/env python3.12
"""Prove that a release directory holds exactly the files of its commit.

    python3.12 verify-release.py /opt/aichat/releases/<commit> [MANIFEST]

MANIFEST is `git ls-tree -r -z --full-tree <commit>` (written by deploy/deploy.sh). For every
file of the commit, the file on disk must have the same git blob hash: edits, deletions,
truncation or line-ending changes after the deploy are all caught. Build output (.venv,
node_modules, .next) is not part of the commit and is not checked. Standard library only;
prints nothing secret.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path


def blob_hash(path: Path, mode: str) -> str:
    data = os.readlink(path).encode() if mode == "120000" else path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324 - git's object id


def main() -> int:
    root = Path(sys.argv[1])
    manifest = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "MANIFEST"
    problems: list[str] = []
    checked = 0
    for entry in manifest.read_bytes().split(b"\0"):
        if not entry:
            continue
        meta, _, name = entry.decode("utf-8").partition("\t")
        mode, kind, expected = meta.split()
        if kind != "blob":
            problems.append(f"unsupported entry ({kind}): {name}")
            continue
        checked += 1
        path = root / name
        try:
            if blob_hash(path, mode) != expected:
                problems.append(f"changed: {name}")
        except OSError:
            problems.append(f"missing: {name}")
    if checked == 0:
        problems.append("the manifest lists no files")
    if problems:
        print(f"release files do NOT match the commit ({len(problems)} problems):", file=sys.stderr)
        for line in problems[:20]:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"    files verified: all {checked} files match the commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
