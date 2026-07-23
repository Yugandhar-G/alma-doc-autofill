"""Checklist state machine: create, submit (answers + docs), review, resubmit."""
from __future__ import annotations

import pytest

from intake_workflow.domain import api
from intake_workflow.schemas import ItemState, PartyRole

P = PartyRole.petitioner
B = PartyRole.beneficiary


def _findings(item):
    return [f.code for f in item.submissions[-1].autocheck.findings]


def test_create_case_items_pending_and_tokens(new_case):
    case = new_case()
    assert case.items and all(i.state == ItemState.pending for i in case.items)
    assert all(p.token for p in case.parties)
    assert len({p.token for p in case.parties}) == 2  # distinct tokens


def test_create_case_writes_timeline(new_case, store):
    case = new_case()
    assert "case_created" in [e.kind for e in store.list_timeline(case.id)]


def test_submit_answers_clean_is_checked_and_records_activity(new_case, store, now):
    case = new_case()
    item = api.submit_answers(store, case, "pet_bio", P, {
        "full_name": "Ana Marquez", "dob": "1988-04-12",
        "phone": "415-555-0100", "address": "1 Alder St, San Jose CA",
    }, now=now)
    assert item.state == ItemState.checked
    assert case.party(P).last_activity_at == now


def test_submit_answers_bad_date_flagged(new_case, store, now):
    case = new_case()
    item = api.submit_answers(store, case, "pet_bio", P, {
        "full_name": "Ana", "dob": "not-a-date", "phone": "x", "address": "y",
    }, now=now)
    assert item.state == ItemState.flagged
    assert "invalid_date" in _findings(item)


def test_submit_answers_missing_required_flagged(new_case, store, now):
    case = new_case()
    item = api.submit_answers(store, case, "pet_bio", P, {
        "dob": "1988-04-12", "phone": "x", "address": "y",  # full_name missing
    }, now=now)
    assert item.state == ItemState.flagged
    assert "missing_field" in _findings(item)


def test_submit_answers_pattern_flagged(new_case, store, now):
    case = new_case()
    item = api.submit_answers(store, case, "ben_bio", B, {
        "full_name": "Wei Chen", "dob": "1990-02-02", "last_entry": "2022-01-01",
        "current_status": "F-1", "a_number": "12",  # violates ^A?\d{8,9}$
    }, now=now)
    assert item.state == ItemState.flagged
    assert "invalid_format" in _findings(item)


def test_submit_answers_optional_blank_ok(new_case, store, now):
    case = new_case()
    # a_number / i94_number omitted (optional) -> clean.
    item = api.submit_answers(store, case, "ben_bio", B, {
        "full_name": "Wei Chen", "dob": "1990-02-02", "last_entry": "2022-01-01",
        "current_status": "F-1",
    }, now=now)
    assert item.state == ItemState.checked


def test_submit_unknown_item_raises_keyerror(new_case, store, now):
    case = new_case()
    with pytest.raises(KeyError):
        api.submit_answers(store, case, "does_not_exist", P, {}, now=now)
    with pytest.raises(KeyError):
        api.submit_document(store, case, "does_not_exist", P, "f.pdf", "/x", now=now)


def test_returned_then_resubmitted_transition(new_case, store, now, make_pdf):
    case = new_case()
    tiny, good = make_pdf("t.pdf", pad_bytes=0), make_pdf("g.pdf")

    item = api.submit_document(store, case, "marriage_cert", P, "m.pdf", tiny, now=now)
    assert item.state == ItemState.flagged  # too_small

    item = api.review_item(store, case, "marriage_cert", action="returned",
                           reviewer="Isaiah",
                           reason="Cut off on the right — please re-scan.", now=now)
    assert item.state == ItemState.returned
    assert item.open is True
    assert item.latest_return_reason == "Cut off on the right — please re-scan."

    # Client resubmits a clean file: returned -> submitted -> checked.
    item = api.submit_document(store, case, "marriage_cert", P, "m2.pdf", good, now=now)
    assert item.state == ItemState.checked
    assert item.open is False
    assert len(item.submissions) == 2

    item = api.review_item(store, case, "marriage_cert", action="accepted",
                           reviewer="Isaiah", now=now)
    assert item.state == ItemState.accepted


def test_review_returned_without_reason_raises(new_case, store, now):
    case = new_case()
    with pytest.raises(ValueError):
        api.review_item(store, case, "marriage_cert", action="returned",
                        reviewer="Isaiah", now=now)
    with pytest.raises(ValueError):
        api.review_item(store, case, "marriage_cert", action="returned",
                        reviewer="Isaiah", reason="   ", now=now)


def test_review_invalid_action_raises(new_case, store, now):
    case = new_case()
    with pytest.raises(ValueError):
        api.review_item(store, case, "marriage_cert", action="maybe",
                        reviewer="Isaiah", now=now)


def test_review_writes_timeline(new_case, store, now):
    case = new_case()
    api.review_item(store, case, "marriage_cert", action="accepted",
                    reviewer="Isaiah", now=now)
    assert "item_accepted" in [e.kind for e in store.list_timeline(case.id)]


def test_state_persists_across_reload(new_case, store, now, make_pdf):
    case = new_case()
    api.submit_document(store, case, "marriage_cert", P, "m.pdf", make_pdf(), now=now)
    reloaded = store.get_case(case.id)
    assert reloaded.item("marriage_cert").state == ItemState.checked
