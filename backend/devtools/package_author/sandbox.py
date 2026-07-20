"""The sandbox — path discipline for the authoring agents, enforced by
construction, not by prompt.

This is the product of Phase E1: agents may DRAFT a vertical package, and the
only filesystem surface they touch is a per-run candidate directory. Two
allow-lists, both resolved to absolute real paths and checked by containment
(``is_relative_to``) so ``..``, symlinks, and absolute paths cannot escape:

- READ: files under ``app/packages/`` or the single file
  ``app/kernel/package.py``. Nothing else is readable.
- WRITE: files under ``app/packages/_candidates/<candidate_id>/`` — the run's
  own sandbox. The live registry (``app/registry.py``) and every shipped
  package are structurally unreachable: a write that resolves outside the
  candidate root returns None here and the tool refuses it.

Pure functions, no I/O — the tools in tools.py own reading/writing; this module
owns only the yes/no of a path. That split keeps the security decision unit
testable without a filesystem and adversarially (see tests/test_package_author).
"""
from __future__ import annotations

import re
from pathlib import Path

# devtools/package_author/sandbox.py → parents[2] is the backend root (the dir
# that contains ``app/``). Resolved so a symlinked checkout still anchors right.
BACKEND_ROOT = Path(__file__).resolve().parents[2]

_PACKAGES_DIR = (BACKEND_ROOT / "app" / "packages").resolve()
_CANDIDATES_DIR = (_PACKAGES_DIR / "_candidates").resolve()
_PACKAGE_PY = (BACKEND_ROOT / "app" / "kernel" / "package.py").resolve()

# A candidate id becomes a directory name and a python module segment, so it is
# a strict slug: lowercase alnum start, then alnum / underscore / hyphen. This
# alone forecloses "..", "/", and absolute paths in the id itself.
_CANDIDATE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def is_valid_candidate_id(candidate_id: str) -> bool:
    return bool(candidate_id) and _CANDIDATE_ID.match(candidate_id) is not None


def candidate_root(candidate_id: str) -> Path:
    """The absolute sandbox root for one run. Raises ValueError on a bad id so
    a traversal-shaped id can never become a path."""
    if not is_valid_candidate_id(candidate_id):
        raise ValueError(f"invalid candidate id: {candidate_id!r}")
    return (_CANDIDATES_DIR / candidate_id).resolve()


def resolve_read_path(relpath: str) -> Path | None:
    """The absolute path a read is allowed to touch, or None to refuse.

    Allowed: any path under app/packages/, plus the exact file
    app/kernel/package.py. Everything else — /etc/passwd, app/registry.py,
    app/kernel/agent.py, ../.. escapes — resolves outside the allow-list and
    returns None."""
    if not relpath:
        return None
    try:
        resolved = (BACKEND_ROOT / relpath).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if resolved == _PACKAGE_PY:
        return resolved
    if resolved != _PACKAGES_DIR and resolved.is_relative_to(_PACKAGES_DIR):
        return resolved
    return None


def resolve_write_path(candidate_id: str, relpath: str) -> Path | None:
    """The absolute path a write is allowed to create, or None to refuse.

    Only files strictly inside the run's candidate root. Absolute paths and any
    relpath that resolves outside the root (``../../registry.py``) return None —
    the structural guarantee the tests hammer adversarially."""
    if not relpath:
        return None
    candidate = Path(relpath)
    # Reject absolute paths outright (pathlib join would discard the root).
    if candidate.is_absolute() or relpath.startswith(("/", "\\")):
        return None
    try:
        root = candidate_root(candidate_id)
    except ValueError:
        return None
    try:
        resolved = (root / candidate).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    # Must land strictly inside the sandbox and name a file (not the root).
    if resolved == root or not resolved.is_relative_to(root):
        return None
    return resolved
