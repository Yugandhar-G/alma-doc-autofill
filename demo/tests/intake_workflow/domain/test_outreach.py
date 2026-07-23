"""Follow-up body generation and the approval-queue actions."""
from __future__ import annotations

from datetime import timedelta

import pytest

from intake_workflow.domain import api
from intake_workflow.schemas import OutreachStatus, PartyRole, Rung

P = PartyRole.petitioner
B = PartyRole.beneficiary


def test_draft_client_lists_returned_and_pending_with_link_and_signature(
        new_case, store, now, make_pdf):
    case = new_case()
    # Return a beneficiary item with a verbatim reason.
    api.submit_document(store, case, "ben_passport", B, "p.pdf",
                        make_pdf("t.pdf", pad_bytes=0), now=now)
    api.review_item(store, case, "ben_passport", action="returned",
                    reviewer="Isaiah",
                    reason="The photo page is blurry — please re-scan.", now=now)

    event = api.draft_followup(case, B, Rung.nudge, now)
    assert event.rung == Rung.nudge
    assert event.party_role == B
    assert event.status == OutreachStatus.drafted  # never auto-sends
    assert "Wei" in event.body  # greeted by first name
    assert "The photo page is blurry — please re-scan." in event.body  # returned reason
    assert "Beneficiary — Passport bio page" in event.body  # a pending item label
    link = f"http://localhost:8000/c/{case.party(B).token}"
    assert link in event.body
    assert "Allison — Yew Legal" in event.body


def test_draft_call_offer_notes_other_spouse_done(new_case, store, now, make_pdf):
    case = new_case()
    from intake_workflow.schemas import ItemKind
    from .conftest import VALID_ANSWERS
    # Finish everything assigned to the petitioner.
    for item in [i for i in case.items if i.assignee == P]:
        if item.kind == ItemKind.question_section:
            api.submit_answers(store, case, item.key, P, VALID_ANSWERS[item.key], now=now)
        else:
            api.submit_document(store, case, item.key, P, "f.pdf", make_pdf(), now=now)
        api.review_item(store, case, item.key, action="accepted", reviewer="Isaiah",
                        now=now)

    event = api.draft_followup(case, B, Rung.call_offer, now)
    assert event.rung == Rung.call_offer
    assert "only" in event.body.lower()  # notes that only the beneficiary's items remain


def test_draft_escalate_is_internal_note_to_allison(new_case, store, now):
    case = new_case()
    case.party(B).last_activity_at = now - timedelta(days=20)
    event = api.draft_followup(case, B, Rung.escalate, now)
    assert event.rung == Rung.escalate
    assert "stalled" in event.subject.lower()
    assert "Allison" in event.body
    assert "20 days" in event.body  # days-inactive summary


def test_draft_followup_does_not_persist(new_case, store, now):
    case = new_case()
    api.draft_followup(case, B, Rung.nudge, now)
    assert store.get_case(case.id).outreach == []


def _draft_one(new_case, store, now):
    case = new_case()
    case.party(B).last_activity_at = now - timedelta(days=5)
    store.save_case(case)
    drafted = api.run_scheduler(store, now=now)
    return store.get_case(case.id), drafted[0].id


def test_approve_outreach_marks_sent(new_case, store, now):
    case, oid = _draft_one(new_case, store, now)
    event = api.approve_outreach(store, case, oid, "Isaiah", now=now)
    assert event.status == OutreachStatus.sent
    assert event.sent_at == now
    assert event.approved_by == "Isaiah"
    assert "outreach_sent" in [e.kind for e in store.list_timeline(case.id)]


def test_dismiss_outreach_marks_dismissed(new_case, store, now):
    case, oid = _draft_one(new_case, store, now)
    event = api.dismiss_outreach(store, case, oid, "Isaiah", now=now)
    assert event.status == OutreachStatus.dismissed
    assert event.approved_by == "Isaiah"
    assert event.sent_at is None


def test_approve_unknown_id_raises_keyerror(new_case, store, now):
    case, _ = _draft_one(new_case, store, now)
    with pytest.raises(KeyError):
        api.approve_outreach(store, case, "no-such-id", "Isaiah", now=now)


def test_approve_non_drafted_raises_valueerror(new_case, store, now):
    case, oid = _draft_one(new_case, store, now)
    api.approve_outreach(store, case, oid, "Isaiah", now=now)
    with pytest.raises(ValueError):  # already sent
        api.approve_outreach(store, case, oid, "Isaiah", now=now)


def test_dismiss_then_approve_raises_valueerror(new_case, store, now):
    case, oid = _draft_one(new_case, store, now)
    api.dismiss_outreach(store, case, oid, "Isaiah", now=now)
    with pytest.raises(ValueError):
        api.approve_outreach(store, case, oid, "Isaiah", now=now)
