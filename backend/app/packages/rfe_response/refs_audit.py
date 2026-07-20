"""Deterministic checklist audit + cover-structure assembly.

The anti-fabrication core of the assembler, mirroring
matter_intake/refs_audit.py: the distillation call proposes checklist items, and
CODE — never the model's word — decides what survives.

- An item whose ``ground_id`` is not one of the parsed notice's grounds is a
  fabricated ground → the whole item is dropped with a warning (the worst defect
  class: an overclaim about what the officer asked).
- An item's ``refs`` are trimmed to {ground_ids} ∪ {matter doc ids shown}; a ref
  outside that set is one the model invented and is stripped (the item survives
  on its valid ground).
- ``cover_structure`` is assembled here from the surviving items — one ordered
  section heading per addressed ground, in the notice's ground order — so the
  cover outline is grounded in audited data, not free LLM prose.

Pure functions, no I/O, no mutation."""
from collections.abc import Iterable

from app.packages.rfe_response.schemas import ChecklistItem, RfeGround


def surviving_refs(refs: Iterable[str], allowed: set[str]) -> list[str]:
    """The subset of ``refs`` inside ``allowed`` (order-preserving). A ref
    outside the allow-list is one the model invented or borrowed."""
    return [r for r in refs if r in allowed]


def audit_checklist(
    items: Iterable[ChecklistItem],
    ground_ids: Iterable[str],
    matter_doc_ids: Iterable[str],
) -> tuple[list[ChecklistItem], list[str]]:
    """Strip fabricated grounds and invented refs from the proposed items.

    Returns (kept_items, warnings). An item citing a ground not in the notice is
    dropped (warned); every surviving item keeps only refs in
    {ground_ids} ∪ {matter_doc_ids}."""
    valid_grounds = set(ground_ids)
    allowed_refs = valid_grounds | set(matter_doc_ids)
    kept: list[ChecklistItem] = []
    warnings: list[str] = []
    for item in items:
        if item.ground_id not in valid_grounds:
            warnings.append(
                f"dropped checklist item for ground {item.ground_id!r}: "
                "that ground is not in the parsed notice (fabricated ground)"
            )
            continue
        valid = surviving_refs(item.refs, allowed_refs)
        if len(valid) != len(item.refs):
            warnings.append(
                f"stripped {len(item.refs) - len(valid)} invented ref(s) from the "
                f"item for ground {item.ground_id!r}"
            )
        kept.append(item.model_copy(update={"refs": valid}))
    return kept, warnings


def _heading(ground: RfeGround) -> str:
    """One cover section heading for a ground. Uses the officer's requested
    evidence (or the quoted text) as the section subject, truncated — the text
    is verbatim from the notice, never model prose."""
    subject = (ground.requested_evidence or ground.quoted_text or "").strip()
    subject = " ".join(subject.split())  # collapse whitespace/newlines
    if len(subject) > 80:
        subject = subject[:77].rstrip() + "..."
    tail = f": {subject}" if subject else ""
    return f"Response to ground {ground.ground_id}{tail}"


def build_cover_structure(
    grounds: Iterable[RfeGround], kept_items: Iterable[ChecklistItem]
) -> list[str]:
    """Ordered cover-letter section headings assembled from audited items.

    A leading cover-letter heading, then one section per ground that at least
    one surviving item addresses, in the notice's ground order — so the outline
    can never reference a ground the response is not actually building."""
    addressed = {item.ground_id for item in kept_items}
    headings = ["Cover letter and response summary"]
    for ground in grounds:
        if ground.ground_id in addressed:
            headings.append(_heading(ground))
    headings.append("Exhibit index and supporting documents")
    return headings
