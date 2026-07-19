"""Reference auditing machinery — strip citations that don't resolve to
ground truth the user actually provided.

The kernel owns the mechanics (normalization, keep/strip accounting); the
calling package owns the validity predicate, because what a valid ref *is*
(intake answer id, doc-hash + verbatim excerpt, transcript-seen URL, memory
record) is package policy.
"""
import re
from typing import Callable, Sequence, TypeVar

_WS = re.compile(r"\s+")

Ref = TypeVar("Ref")


def normalize(text: str) -> str:
    """Whitespace-collapsed, lowercased — the canonical form for excerpt
    substring matching (a doc citation must quote the document)."""
    return _WS.sub(" ", text).strip().lower()


def audit_refs(
    refs: Sequence[Ref], is_valid: Callable[[Ref], bool]
) -> tuple[list[Ref], int]:
    """(surviving refs, number stripped). Deterministic, order-preserving."""
    kept = [ref for ref in refs if is_valid(ref)]
    return kept, len(refs) - len(kept)
