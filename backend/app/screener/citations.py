"""Deterministic citation audit — the screener's anti-fabrication guardrail.

Runs in assemble_report, after all LLM output has parsed. Every SourceRef is
verified against what the user actually provided:

  kind=answer → ref must name a non-empty intake answer
  kind=doc    → ref must be an uploaded document's hash AND the excerpt must
                substring-match (whitespace-normalized) that document's
                extracted key_facts
  kind=web    → ref must be a URL the enrichment tool actually returned

Invalid refs are stripped. An assessment whose verdict is better than not_met
but which retains zero valid citations is downgraded to not_met with a
warning — the screener version of "a null is correct; a plausible guess is a
defect". Models are never mutated (model_copy only).
"""
from app.kernel.audit.refs import audit_refs as _kernel_audit_refs
from app.kernel.audit.refs import normalize as _normalize
from app.schemas import (
    CriterionAssessment,
    EvidenceDocRecord,
    FieldWarning,
    FinalMeritsAssessment,
    SourceRef,
)
from app.screener.intake import is_valid_answer_ref


def _doc_corpus(docs: list[EvidenceDocRecord]) -> dict[str, str]:
    """hash → normalized searchable text of everything extracted from it."""
    return {
        doc.source_hash: _normalize(" | ".join([doc.title or "", *doc.key_facts]))
        for doc in docs
    }


def _ref_is_valid(
    ref: SourceRef,
    valid_answer_ids: frozenset[str],
    corpus: dict[str, str],
    grounded_urls: frozenset[str],
) -> bool:
    if ref.kind == "answer":
        return is_valid_answer_ref(ref.ref, valid_answer_ids)
    if ref.kind == "doc":
        text = corpus.get(ref.ref)
        if text is None:
            return False
        # A doc citation must quote the document, not merely point at it.
        return bool(ref.excerpt) and _normalize(ref.excerpt) in text
    if ref.kind == "web":
        return ref.ref in grounded_urls
    return False


def audit_refs(
    refs: list[SourceRef],
    valid_answer_ids: frozenset[str],
    corpus: dict[str, str],
    grounded_urls: frozenset[str],
) -> tuple[list[SourceRef], int]:
    """(surviving refs, number stripped). Mechanics live in kernel.audit;
    this module owns only the validity policy (_ref_is_valid)."""
    return _kernel_audit_refs(
        refs, lambda ref: _ref_is_valid(ref, valid_answer_ids, corpus, grounded_urls)
    )


def audit_assessment(
    assessment: CriterionAssessment,
    valid_answer_ids: frozenset[str],
    docs: list[EvidenceDocRecord],
    grounded_urls: frozenset[str],
) -> tuple[CriterionAssessment, list[FieldWarning]]:
    """Strip unverifiable citations; downgrade uncited positive verdicts."""
    corpus = _doc_corpus(docs)
    kept, stripped = audit_refs(
        assessment.citations, valid_answer_ids, corpus, grounded_urls
    )
    warnings: list[FieldWarning] = []
    if stripped:
        warnings.append(
            FieldWarning(
                field=f"assessments.{assessment.criterion_id}.citations",
                message=f"{stripped} citation(s) did not match any provided "
                "evidence and were removed.",
            )
        )
    updated = assessment.model_copy(update={"citations": kept})
    if updated.verdict != "not_met" and not kept:
        warnings.append(
            FieldWarning(
                field=f"assessments.{assessment.criterion_id}.verdict",
                message=f"Verdict '{assessment.verdict}' had no verifiable "
                "citation and was downgraded to not_met. Uncited claims are "
                "treated as unsupported.",
            )
        )
        updated = updated.model_copy(update={"verdict": "not_met"})
    return updated, warnings


def audit_final_merits(
    merits: FinalMeritsAssessment,
    valid_answer_ids: frozenset[str],
    docs: list[EvidenceDocRecord],
    grounded_urls: frozenset[str],
) -> tuple[FinalMeritsAssessment, list[FieldWarning]]:
    """Same strip rule; a favorable conclusion without citations degrades to
    uncertain (never silently favorable on nothing)."""
    corpus = _doc_corpus(docs)
    kept, stripped = audit_refs(merits.citations, valid_answer_ids, corpus, grounded_urls)
    warnings: list[FieldWarning] = []
    if stripped:
        warnings.append(
            FieldWarning(
                field="final_merits.citations",
                message=f"{stripped} citation(s) did not match any provided "
                "evidence and were removed.",
            )
        )
    updated = merits.model_copy(update={"citations": kept})
    if updated.conclusion == "favorable" and not kept:
        warnings.append(
            FieldWarning(
                field="final_merits.conclusion",
                message="A favorable final-merits conclusion had no verifiable "
                "citation and was downgraded to uncertain.",
            )
        )
        updated = updated.model_copy(update={"conclusion": "uncertain"})
    return updated, warnings
