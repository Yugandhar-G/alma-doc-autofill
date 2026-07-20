"""Deterministic transcript-audit primitives shared by the firm-data agents.

The firm-data analog of app.kernel.audit.transcript (which audits web evidence
URLs against seen_urls): here every citation must resolve against
transcript.seen_refs — the doc_ids / memory ids a tool ACTUALLY surfaced this
run — and every uncited "missing" claim must survive a CODE check against the
store, never the model's word.

Pure functions, no I/O, no mutation."""
from collections.abc import Iterable


def surviving_refs(refs: Iterable[str], seen_refs: Iterable[str]) -> list[str]:
    """The subset of ``refs`` the agent actually saw (order-preserving). A ref
    outside seen_refs is one the model invented or cross-firm-borrowed."""
    seen = set(seen_refs)
    return [r for r in refs if r in seen]


def normalize_kind(doc_kind: str) -> str:
    """Case/space-insensitive doc-kind key for store comparisons."""
    return doc_kind.strip().lower()


def is_code_verified_absence(
    doc_kind: str, required_types: set[str], present_types: set[str]
) -> bool:
    """True only when the store CONFIRMS a genuine gap: ``doc_kind`` is a
    required document for the case type AND no document of that type is attached.

    A claim about a doc_kind that is present is the fabrication class (handled by
    the caller as a dropped + warned finding); a claim about a doc_kind that is
    not even in the requirements registry is an uncited guess and does not
    survive — the registry is the ground truth for what "required" means."""
    dk = normalize_kind(doc_kind)
    return dk in required_types and dk not in present_types
