"""approve_outreach provider behavior (phase 2 auto-send-on-approval)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from intake_workflow.domain import api
from intake_workflow.email.outbox import EmailSendError
from intake_workflow.schemas import OutreachStatus, PartyRole, Rung

from .conftest import FailingProvider, FakeProvider

B = PartyRole.beneficiary


def _draft_client_rung(new_case, store, now, rung=Rung.nudge):
    """Draft (persist) one client-facing follow-up for the beneficiary."""
    case = new_case()
    case.party(B).last_activity_at = now - timedelta(days=20)
    event = api.draft_followup(case, B, rung, now)
    case.outreach.append(event)
    store.save_case(case)
    return case, event.id


def test_approve_with_provider_sends_to_party_and_records(new_case, store, now):
    case, oid = _draft_client_rung(new_case, store, now, Rung.nudge)
    provider = FakeProvider(name="fake", message_id="gmail-abc123")

    event = api.approve_outreach(store, case, oid, "Isaiah", now=now, provider=provider)

    # Sent to the beneficiary's real email, exactly once, with the drafted body.
    assert len(provider.calls) == 1
    assert provider.calls[0]["to_email"] == case.party(B).email == "b@example.com"
    assert provider.calls[0]["subject"] == event.subject
    assert provider.calls[0]["body"] == event.body

    # Provenance recorded on the event and persisted.
    assert event.status == OutreachStatus.sent
    assert event.sent_via == "fake"
    assert event.message_id == "gmail-abc123"
    reloaded = store.get_case(case.id).outreach[0]
    assert reloaded.sent_via == "fake"
    assert reloaded.message_id == "gmail-abc123"
    assert reloaded.status == OutreachStatus.sent


def test_approve_send_failure_leaves_drafted_and_reraises(new_case, store, now):
    case, oid = _draft_client_rung(new_case, store, now, Rung.nudge)
    provider = FailingProvider()

    with pytest.raises(EmailSendError):
        api.approve_outreach(store, case, oid, "Isaiah", now=now, provider=provider)

    # The persisted event stays drafted with no provenance — falls back to queue.
    reloaded = store.get_case(case.id).outreach[0]
    assert reloaded.status == OutreachStatus.drafted
    assert reloaded.sent_via is None
    assert reloaded.message_id is None
    assert reloaded.sent_at is None


def test_approve_escalate_with_provider_is_record_only(new_case, store, now):
    # Escalate is an internal note: recorded, never emailed, even with a provider.
    case = new_case()
    case.party(B).last_activity_at = now - timedelta(days=20)
    event = api.draft_followup(case, B, Rung.escalate, now)
    case.outreach.append(event)
    store.save_case(case)
    provider = FakeProvider()

    result = api.approve_outreach(store, case, event.id, "Isaiah", now=now,
                                  provider=provider)

    assert provider.calls == []            # no email attempted
    assert result.status == OutreachStatus.sent
    assert result.sent_via is None         # recorded only
    assert result.message_id is None
    assert result.approved_by == "Isaiah"


def test_approve_without_provider_is_record_only(new_case, store, now):
    # Phase-1 behavior must be preserved byte-for-byte when no provider is given.
    case, oid = _draft_client_rung(new_case, store, now, Rung.nudge)

    event = api.approve_outreach(store, case, oid, "Isaiah", now=now)

    assert event.status == OutreachStatus.sent
    assert event.sent_at == now
    assert event.approved_by == "Isaiah"
    assert event.sent_via is None
    assert event.message_id is None
    assert "outreach_sent" in [e.kind for e in store.list_timeline(case.id)]
