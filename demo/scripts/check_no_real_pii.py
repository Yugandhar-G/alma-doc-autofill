#!/usr/bin/env python3
"""Pre-commit PII guard — CLAUDE_WORKPLAN.md §4.4.

The real recordings/transcripts contain actual client names. Those must NEVER
enter this codebase — fictional cast only. This scans the *staged* content of
files under demo/ for the known real names and exits 2 (loud) if any appears.

Scope: git diff --cached, restricted to paths under demo/.
Match: case-insensitive substring against the staged blob content.
"""

from __future__ import annotations

import base64
import subprocess
import sys

# Known real names/handles that must never be committed (case-insensitive).
# Base64-encoded so the plaintext strings never appear in the repo — the guard
# must not itself violate the rule it enforces (workplan §4.4).
_FORBIDDEN_B64: tuple[str, ...] = ("QW5kcmV3IEhl", "Q2hlbmcgTmll", "YW5kcmV3aGU=")
FORBIDDEN: tuple[str, ...] = tuple(
    base64.b64decode(p).decode("utf-8") for p in _FORBIDDEN_B64
)

DEMO_PREFIX = "demo/"


def _staged_demo_files() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.splitlines() if p.strip().startswith(DEMO_PREFIX)]


def _staged_content(path: str) -> str:
    # Read the staged blob (index version), not the working tree.
    result = subprocess.run(
        ["git", "show", f":{path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Binary/removed/unreadable staged blob — nothing textual to scan.
        return ""
    return result.stdout


def main() -> int:
    try:
        files = _staged_demo_files()
    except subprocess.CalledProcessError as exc:
        print(f"[pii-guard] FAILED to list staged files: {exc}", file=sys.stderr)
        return 2

    needles = [(name, name.lower()) for name in FORBIDDEN]
    hits: list[tuple[str, str]] = []

    for path in files:
        haystack = _staged_content(path).lower()
        if not haystack:
            continue
        for original, needle in needles:
            if needle in haystack:
                hits.append((path, original))

    if hits:
        print("=" * 70, file=sys.stderr)
        print("[pii-guard] BLOCKED: real client PII found in staged demo/ files.",
              file=sys.stderr)
        print("Fictional cast ONLY (workplan §4.4). Remove these before committing:",
              file=sys.stderr)
        for path, name in hits:
            print(f"   - {path}: contains {name!r}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
