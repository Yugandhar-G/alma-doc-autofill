"""Transcript-evidence auditing — agent conclusions may only cite what the
agent actually saw.

Generic over any Pydantic item carrying `evidence_urls` and `status`: URLs
absent from the transcript's seen-set are stripped, and a strong status with
no surviving evidence falls back to the neutral status. Absence of evidence
is neutral ("unverified"), never negative — the audit can weaken claims, it
never manufactures contradiction.
"""
from typing import Iterable, Sequence, TypeVar

from pydantic import BaseModel

Item = TypeVar("Item", bound=BaseModel)

_DEFAULT_STRONG = ("verified", "partially_verified", "contradicted")


def audit_evidence_urls(
    items: Sequence[Item],
    seen_urls: Iterable[str],
    *,
    strong_statuses: tuple[str, ...] = _DEFAULT_STRONG,
    fallback_status: str = "unverified",
) -> list[Item]:
    """Strip transcript-unseen URLs; downgrade evidence-less strong statuses.
    Items are never mutated (model_copy only)."""
    seen = set(seen_urls)
    audited: list[Item] = []
    for item in items:
        urls = [url for url in item.evidence_urls if url in seen]  # type: ignore[attr-defined]
        status = item.status  # type: ignore[attr-defined]
        if status in strong_statuses and not urls:
            status = fallback_status
        audited.append(item.model_copy(update={"evidence_urls": urls, "status": status}))
    return audited
