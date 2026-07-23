"""Post-filing tracking: filings, receipt validation, status updates, and the
client status-update outreach draft."""
from __future__ import annotations

from datetime import date

import pytest

from intake_workflow.domain import filings
from intake_workflow.schemas import Milestone, OutreachStatus, PartyRole, Rung

B = PartyRole.beneficiary
FILED = date(2026, 1, 15)


# --------------------------------------------------------------------- record_filing

def test_record_filing_normalizes_form_type_and_seeds_initial_update(
        new_case, store, now):
    case = new_case()
    rec = filings.record_filing(case=case, store=store, form_type="i-130",
                                filed_on=FILED, now=now)
    assert rec.form_type == "I-130"                 # normalized upper-case
    assert rec.status == Milestone.filed
    assert [u.milestone for u in rec.updates] == [Milestone.filed]
    # Persisted on the case and mirrored to the timeline.
    assert store.get_case(case.id).filings[0].id == rec.id
    kinds = [e.kind for e in store.list_timeline(case.id)]
    assert "filing_recorded" in kinds


def test_record_filing_accepts_good_receipt_and_lowercases(new_case, store, now):
    case = new_case()
    rec = filings.record_filing(store, case, form_type="I-130", filed_on=FILED,
                                receipt_number="ioe0123456789", now=now)
    assert rec.receipt_number == "IOE0123456789"    # normalized after strip/upper


def test_record_filing_rejects_bad_receipt(new_case, store, now):
    case = new_case()
    with pytest.raises(ValueError):
        filings.record_filing(store, case, form_type="I-130", filed_on=FILED,
                              receipt_number="12345", now=now)


# ----------------------------------------------------------------- set_receipt_number

def test_set_receipt_number_transitions_filed_to_receipt(new_case, store, now):
    case = new_case()
    rec = filings.record_filing(store, case, form_type="I-130", filed_on=FILED,
                                now=now)
    assert rec.status == Milestone.filed
    updated = filings.set_receipt_number(store, case, rec.id, "IOE0123456789",
                                         now=now)
    assert updated.receipt_number == "IOE0123456789"
    assert updated.status == Milestone.receipt
    assert updated.updates[-1].milestone == Milestone.receipt


def test_set_receipt_number_does_not_downgrade_from_later_milestone(
        new_case, store, now):
    case = new_case()
    rec = filings.record_filing(store, case, form_type="I-130", filed_on=FILED,
                                now=now)
    filings.update_filing_status(store, case, rec.id,
                                 milestone=Milestone.biometrics, now=now)
    updated = filings.set_receipt_number(store, case, rec.id, "IOE0123456789",
                                         now=now)
    # Receipt update is appended, but status stays at the later milestone.
    assert updated.status == Milestone.biometrics
    assert updated.updates[-1].milestone == Milestone.receipt
    assert updated.receipt_number == "IOE0123456789"


def test_set_receipt_number_rejects_bad_receipt(new_case, store, now):
    case = new_case()
    rec = filings.record_filing(store, case, form_type="I-130", filed_on=FILED,
                                now=now)
    with pytest.raises(ValueError):
        filings.set_receipt_number(store, case, rec.id, "nope", now=now)


def test_set_receipt_number_unknown_filing_raises_keyerror(new_case, store, now):
    case = new_case()
    with pytest.raises(KeyError):
        filings.set_receipt_number(store, case, "no-such-filing",
                                   "IOE0123456789", now=now)


# ---------------------------------------------------------------- update_filing_status

def test_update_filing_status_appends_and_sets_status(new_case, store, now):
    case = new_case()
    rec = filings.record_filing(store, case, form_type="I-130", filed_on=FILED,
                                now=now)
    updated = filings.update_filing_status(
        store, case, rec.id, milestone=Milestone.interview,
        note="Interview scheduled.", now=now)
    assert updated.status == Milestone.interview
    assert updated.updates[-1].milestone == Milestone.interview
    assert updated.updates[-1].note == "Interview scheduled."
    # Persisted.
    assert store.get_case(case.id).filings[0].status == Milestone.interview


def test_update_filing_status_unknown_filing_raises_keyerror(new_case, store, now):
    case = new_case()
    with pytest.raises(KeyError):
        filings.update_filing_status(store, case, "no-such-filing",
                                     milestone=Milestone.approved, now=now)


# --------------------------------------------------------------- draft_status_update

def test_draft_status_update_persists_beneficiary_addressed_draft(
        new_case, store, now):
    case = new_case()
    rec = filings.record_filing(store, case, form_type="I-130", filed_on=FILED,
                                receipt_number="IOE0123456789", now=now)
    filings.update_filing_status(store, case, rec.id,
                                 milestone=Milestone.biometrics, now=now)
    event = filings.draft_status_update(store, case, rec.id, now=now)

    assert event.rung == Rung.status_update
    assert event.party_role == B                      # addressed to the beneficiary
    assert event.status == OutreachStatus.drafted     # flows through the queue
    # Persisted into the same outreach list every other draft uses.
    persisted = store.get_case(case.id).outreach
    assert [o.id for o in persisted] == [event.id]

    body = event.body
    assert "biometrics" in body.lower()               # names the milestone
    assert "IOE0123456789" in body                    # receipt number included
    assert filings.USCIS_STATUS_URL in body           # self-tracking link
    assert "Allison — Yew Legal" in body              # signature
    # Never invents dates: the filed date / update timestamps do not leak in.
    assert FILED.isoformat() not in body
    assert "2026-01" not in body


def test_draft_status_update_without_receipt_omits_link(new_case, store, now):
    case = new_case()
    rec = filings.record_filing(store, case, form_type="I-485", filed_on=FILED,
                                now=now)
    event = filings.draft_status_update(store, case, rec.id, now=now)
    assert "filed" in event.body.lower()              # names the (filed) milestone
    assert filings.USCIS_STATUS_URL not in event.body
    assert "receipt number" not in event.body.lower()


def test_draft_status_update_unknown_filing_raises_keyerror(new_case, store, now):
    case = new_case()
    with pytest.raises(KeyError):
        filings.draft_status_update(store, case, "no-such-filing", now=now)
