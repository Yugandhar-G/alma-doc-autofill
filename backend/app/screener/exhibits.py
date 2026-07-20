"""Deterministic exhibit-index derivation — pure code, no LLM.

The exhibit index is the attorney-facing draft of "which evidence supports
which criterion", numbered like an exhibit list. It is built entirely from the
audited evidence matrix: every matrix item's *surviving* sources become
numbered entries, grouped per criterion in registry order.

Post-audit guarantee. The screener's authoritative citation audit runs inside
assemble_report (audit_assessment / audit_refs). That audit is a pure,
deterministic, idempotent function of (refs, valid_answer_ids, doc corpus,
grounded_urls). Re-applying the *same* validity policy here — via the shared
audit_refs — yields exactly the surviving refs assemble_report would keep, so
building exhibits from a re-audit at this node is equivalent to building them
from assemble_report's post-audit artifacts, without needing this node to run
after assemble_report (it cannot — it is upstream). A ref that would be
stripped can therefore never appear as an exhibit.

Numbering is stable: criterion order comes from the registry (the order in
`applicable_ids`), then matrix order within each criterion, then source order
within each item. Documents are referenced by source_hash in doc_ref;
answer/web evidence is identified by source_kind + claim only.
"""
from app.schemas import EvidenceMatrix, ExhibitEntry, ExhibitIndex, SourceRef
from app.screener.citations import _doc_corpus, audit_refs


def _note_for(ref: SourceRef) -> str:
    """Human-readable provenance for the entry without duplicating doc_ref.

    Docs already expose their hash via doc_ref, so the note carries the
    verbatim excerpt (what the citation actually quotes); answer/web evidence
    has no doc_ref, so the note carries the underlying answer_id / url."""
    if ref.kind == "doc":
        return f'"{ref.excerpt}"' if ref.excerpt else ""
    if ref.kind == "answer":
        return f"intake answer: {ref.ref}"
    return f"web: {ref.ref}"


def build_exhibit_index(
    matrix: EvidenceMatrix | None,
    applicable_ids: list[str],
    valid_answer_ids: frozenset[str],
    docs: list,
    grounded_urls: frozenset[str],
) -> ExhibitIndex:
    """Derive the numbered exhibit index from the audited matrix.

    entries: one per (criterion, matrix item, surviving source), numbered in
    registry→matrix→source order.
    gaps: applicable criterion ids with zero surviving entries.
    """
    corpus = _doc_corpus(docs)
    items = matrix.items if matrix is not None else []

    entries: list[ExhibitEntry] = []
    covered: set[str] = set()
    number = 0
    for criterion_id in applicable_ids:  # registry order → stable numbering
        for item in items:  # matrix order
            if criterion_id not in item.criterion_ids:
                continue
            # Re-audit this item's sources with the same policy assemble_report
            # uses; a stripped ref never becomes an exhibit.
            surviving, _ = audit_refs(
                item.sources, valid_answer_ids, corpus, grounded_urls
            )
            for ref in surviving:
                number += 1
                entries.append(
                    ExhibitEntry(
                        exhibit_no=str(number),
                        criterion_id=criterion_id,
                        claim=item.claim,
                        doc_ref=ref.ref if ref.kind == "doc" else None,
                        source_kind=ref.kind,
                        note=_note_for(ref),
                    )
                )
                covered.add(criterion_id)

    gaps = [cid for cid in applicable_ids if cid not in covered]
    return ExhibitIndex(entries=entries, gaps=gaps)
