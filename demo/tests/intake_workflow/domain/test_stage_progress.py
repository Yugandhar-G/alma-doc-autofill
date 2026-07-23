"""Stage detection precedence and progress/coverage math."""
from __future__ import annotations

from datetime import timedelta

from intake_workflow.domain import api
from intake_workflow.schemas import CaseStage, ItemKind, ItemState, PartyRole

from .conftest import VALID_ANSWERS

P = PartyRole.petitioner
B = PartyRole.beneficiary


def _submit_all_required(store, case, now, good_pdf):
    """Submit every required item with valid content -> all checked (none open)."""
    for item in [i for i in case.items if i.required]:
        if item.kind == ItemKind.question_section:
            api.submit_answers(store, case, item.key, item.assignee,
                               VALID_ANSWERS[item.key], now=now)
        else:
            api.submit_document(store, case, item.key, item.assignee,
                                f"{item.key}.pdf", good_pdf, now=now)


def _accept_all_required(store, case, now):
    for item in [i for i in case.items if i.required]:
        api.review_item(store, case, item.key, action="accepted",
                        reviewer="Isaiah", now=now)


def test_stage_sent(new_case, now):
    assert api.detect_stage(new_case(), now) == CaseStage.sent


def test_stage_opened(new_case, store, now):
    case = new_case()
    api.record_activity(store, case, P, now)
    assert api.detect_stage(case, now) == CaseStage.opened


def test_stage_in_progress(new_case, store, now, make_pdf):
    case = new_case()
    api.submit_document(store, case, "marriage_cert", P, "m.pdf", make_pdf(), now=now)
    assert api.detect_stage(case, now) == CaseStage.in_progress


def test_stage_stalled(new_case, store, now):
    case = new_case()
    # Beneficiary has open required assigned items and has gone quiet >= stall_days.
    case.party(B).last_activity_at = now - timedelta(days=case.policy.stall_days)
    assert api.detect_stage(case, now) == CaseStage.stalled


def test_stage_not_stalled_before_threshold(new_case, store, now):
    case = new_case()
    case.party(B).last_activity_at = now - timedelta(days=case.policy.stall_days - 1)
    # No submissions yet, but there is activity -> opened, not stalled.
    assert api.detect_stage(case, now) == CaseStage.opened


def test_stage_ready_for_review(new_case, store, now, make_pdf):
    case = new_case()
    _submit_all_required(store, case, now, make_pdf())
    # Every required item checked (none pending/returned) but none accepted yet.
    assert api.detect_stage(case, now) == CaseStage.ready_for_review


def test_stage_complete(new_case, store, now, make_pdf):
    case = new_case()
    _submit_all_required(store, case, now, make_pdf())
    _accept_all_required(store, case, now)
    assert api.detect_stage(case, now) == CaseStage.complete


def test_precedence_complete_beats_stalled(new_case, store, now, make_pdf):
    case = new_case()
    _submit_all_required(store, case, now, make_pdf())
    _accept_all_required(store, case, now)
    # Even with an ancient last-activity, complete wins (nothing is open).
    case.party(B).last_activity_at = now - timedelta(days=90)
    assert api.detect_stage(case, now) == CaseStage.complete


def test_precedence_ready_for_review_beats_stalled(new_case, store, now, make_pdf):
    case = new_case()
    _submit_all_required(store, case, now, make_pdf())
    case.party(B).last_activity_at = now - timedelta(days=90)
    # No required item is open, so ready_for_review outranks stalled.
    assert api.detect_stage(case, now) == CaseStage.ready_for_review


def test_progress_percent_and_stage(new_case, store, now, make_pdf):
    case = new_case()
    required = [i for i in case.items if i.required]
    # Accept exactly half of the required items.
    half = required[: len(required) // 2]
    for item in half:
        if item.kind == ItemKind.question_section:
            api.submit_answers(store, case, item.key, item.assignee,
                               VALID_ANSWERS[item.key], now=now)
        else:
            api.submit_document(store, case, item.key, item.assignee, "f.pdf",
                                make_pdf(), now=now)
        api.review_item(store, case, item.key, action="accepted",
                        reviewer="Isaiah", now=now)

    prog = api.case_progress(case, now)
    assert prog.required_total == len(required)
    assert prog.accepted == len(half)
    assert prog.percent == int(len(half) * 100 / len(required))


def test_progress_coverage_meter(new_case, store, now, make_pdf):
    case = new_case()
    good = make_pdf()
    # Accept one document in each of 3 distinct bona-fide categories.
    # joint_bank=financial, lease=cohabitation, insurance=insurance.
    for key in ("joint_bank", "lease", "insurance"):
        item = case.item(key)
        api.submit_document(store, case, key, item.assignee, f"{key}.pdf", good, now=now)
        api.review_item(store, case, key, action="accepted", reviewer="Isaiah", now=now)

    prog = api.case_progress(case, now)
    met = {c.category for c in prog.coverage if c.met}
    assert {"financial", "cohabitation", "insurance"} <= met
    assert prog.coverage_met is True  # min_categories == 3


def test_progress_coverage_only_counts_accepted(new_case, store, now, make_pdf):
    case = new_case()
    # Submit but do NOT accept -> category not met.
    api.submit_document(store, case, "joint_bank", P, "jb.pdf", make_pdf(), now=now)
    prog = api.case_progress(case, now)
    financial = next(c for c in prog.coverage if c.category == "financial")
    assert financial.accepted == 0
    assert financial.met is False


def test_progress_coverage_categories_are_documents_only(new_case, now):
    case = new_case()
    prog = api.case_progress(case, now)
    # Five bona-fide categories exist; none met on a fresh case.
    assert len(prog.coverage) == 5
    assert all(c.met is False for c in prog.coverage)
    assert prog.coverage_met is False
