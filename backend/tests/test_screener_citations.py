"""Citation audit — the anti-fabrication guardrail must strip and downgrade
deterministically. Pure tests, no LLM."""
from app.schemas import (
    CriterionAssessment,
    EvidenceDocRecord,
    FinalMeritsAssessment,
    IntakeAnswers,
    SourceRef,
)
from app.screener.citations import audit_assessment, audit_final_merits
from app.screener.intake import answer_index, render_intake

DOC = EvidenceDocRecord(
    source_hash="a" * 64,
    document_kind_detected="award",
    title="Best Paper Award",
    key_facts=["Awarded the Best Paper Award at NeurIPS 2023", "Selected from 12,000 submissions"],
)

INTAKE = IntakeAnswers(
    field_of_endeavor="Machine learning systems",
    awards=["Best Paper NeurIPS 2023", "ACM Distinguished Award"],
)
ANSWER_IDS = frozenset(answer_index(INTAKE).keys())


def _assessment(verdict="likely", citations=()):
    return CriterionAssessment(
        criterion_id="awards", verdict=verdict, reasoning="r", citations=list(citations)
    )


def test_answer_index_addresses_scalars_and_list_entries():
    ids = answer_index(INTAKE)
    assert ids["field_of_endeavor"] == "Machine learning systems"
    assert ids["awards[0]"] == "Best Paper NeurIPS 2023"
    assert ids["awards[1]"] == "ACM Distinguished Award"
    assert "salary_context" not in ids  # empty answers are unaddressable


def test_render_intake_prefixes_answer_ids():
    rendered = render_intake(INTAKE)
    assert "[awards[0]] Best Paper NeurIPS 2023" in rendered


def test_valid_answer_citation_survives():
    a = _assessment(citations=[SourceRef(kind="answer", ref="awards[0]")])
    audited, warnings = audit_assessment(a, ANSWER_IDS, [], frozenset())
    assert audited.verdict == "likely"
    assert len(audited.citations) == 1
    assert warnings == []


def test_unknown_answer_ref_is_stripped_and_verdict_downgraded():
    a = _assessment(citations=[SourceRef(kind="answer", ref="publications_summary")])
    audited, warnings = audit_assessment(a, ANSWER_IDS, [], frozenset())
    assert audited.citations == []
    assert audited.verdict == "not_met"
    fields = [w.field for w in warnings]
    assert "assessments.awards.citations" in fields
    assert "assessments.awards.verdict" in fields


def test_doc_citation_requires_verbatim_excerpt():
    good = SourceRef(kind="doc", ref=DOC.source_hash, excerpt="Best Paper Award at NeurIPS 2023")
    paraphrase = SourceRef(kind="doc", ref=DOC.source_hash, excerpt="won a top ML conference prize")
    no_excerpt = SourceRef(kind="doc", ref=DOC.source_hash)
    a = _assessment(verdict="met", citations=[good, paraphrase, no_excerpt])
    audited, _ = audit_assessment(a, ANSWER_IDS, [DOC], frozenset())
    assert audited.verdict == "met"
    assert [c.excerpt for c in audited.citations] == ["Best Paper Award at NeurIPS 2023"]


def test_doc_excerpt_match_is_whitespace_and_case_insensitive():
    ref = SourceRef(
        kind="doc", ref=DOC.source_hash, excerpt="  best paper award\nat neurips 2023 "
    )
    a = _assessment(verdict="met", citations=[ref])
    audited, _ = audit_assessment(a, ANSWER_IDS, [DOC], frozenset())
    assert audited.citations != []


def test_unknown_doc_hash_is_stripped():
    ref = SourceRef(kind="doc", ref="b" * 64, excerpt="Best Paper Award")
    a = _assessment(citations=[ref])
    audited, _ = audit_assessment(a, ANSWER_IDS, [DOC], frozenset())
    assert audited.citations == []
    assert audited.verdict == "not_met"


def test_web_citation_valid_only_when_grounded():
    url = "https://example.org/coverage"
    a = _assessment(citations=[SourceRef(kind="web", ref=url)])
    audited_ok, _ = audit_assessment(a, ANSWER_IDS, [], frozenset({url}))
    assert audited_ok.citations != []
    audited_bad, _ = audit_assessment(a, ANSWER_IDS, [], frozenset())
    assert audited_bad.citations == []
    assert audited_bad.verdict == "not_met"


def test_not_met_with_no_citations_needs_no_downgrade_warning():
    a = _assessment(verdict="not_met")
    audited, warnings = audit_assessment(a, ANSWER_IDS, [], frozenset())
    assert audited.verdict == "not_met"
    assert warnings == []


def test_favorable_merits_without_citations_degrades_to_uncertain():
    merits = FinalMeritsAssessment(
        conclusion="favorable",
        reasoning="r",
        citations=[SourceRef(kind="answer", ref="never_asked")],
    )
    audited, warnings = audit_final_merits(merits, ANSWER_IDS, [], frozenset())
    assert audited.conclusion == "uncertain"
    assert any(w.field == "final_merits.conclusion" for w in warnings)


def test_models_are_not_mutated():
    ref = SourceRef(kind="answer", ref="nope")
    a = _assessment(citations=[ref])
    audit_assessment(a, ANSWER_IDS, [], frozenset())
    assert a.citations == [ref]  # original untouched (immutability contract)
