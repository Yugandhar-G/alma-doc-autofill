"""run_scheduler auto-send behavior (phase 2 trust ramp)."""
from __future__ import annotations

from datetime import timedelta

from intake_workflow.domain import api
from intake_workflow.schemas import OutreachStatus, PartyRole, Rung

from .conftest import FailingProvider, FakeProvider

B = PartyRole.beneficiary


def _stalled_case(new_case, store, now, days, auto_send_rungs=None):
    """Fresh case whose beneficiary went quiet ``days`` ago, with an auto-send
    policy applied."""
    case = new_case()
    case.party(B).last_activity_at = now - timedelta(days=days)
    if auto_send_rungs is not None:
        case.policy.auto_send_rungs = list(auto_send_rungs)
    store.save_case(case)
    return case


def _bene(events):
    return [e for e in events if e.party_role == B]


def test_autosends_rung_in_policy(new_case, store, now):
    # Day 5 -> nudge, and nudge is opted into auto-send.
    case = _stalled_case(new_case, store, now, 5, auto_send_rungs=[Rung.nudge])
    provider = FakeProvider(name="fake", message_id="m-1")

    drafted = _bene(api.run_scheduler(store, now=now, provider=provider))

    assert len(drafted) == 1
    assert drafted[0].rung == Rung.nudge
    assert len(provider.calls) == 1
    assert provider.calls[0]["to_email"] == case.party(B).email

    sent = store.get_case(case.id).outreach[0]
    assert sent.status == OutreachStatus.sent
    assert sent.approved_by == "scheduler:auto"
    assert sent.sent_via == "fake"
    assert sent.message_id == "m-1"
    kinds = [e.kind for e in store.list_timeline(case.id)]
    assert "outreach_drafted" in kinds and "outreach_sent" in kinds


def test_does_not_autosend_rung_not_in_policy(new_case, store, now):
    # Day 8 -> specifics, but only nudge is opted in: specifics stays drafted.
    case = _stalled_case(new_case, store, now, 8, auto_send_rungs=[Rung.nudge])
    provider = FakeProvider()

    drafted = _bene(api.run_scheduler(store, now=now, provider=provider))

    assert drafted[0].rung == Rung.specifics
    assert provider.calls == []
    assert store.get_case(case.id).outreach[0].status == OutreachStatus.drafted


def test_never_autosends_escalate_even_if_listed(new_case, store, now):
    # Day 20 -> escalate. Even if a misconfigured policy lists escalate, the
    # domain layer refuses to auto-send it.
    case = _stalled_case(new_case, store, now, 20, auto_send_rungs=[Rung.escalate])
    provider = FakeProvider()

    drafted = _bene(api.run_scheduler(store, now=now, provider=provider))

    assert drafted[0].rung == Rung.escalate
    assert provider.calls == []
    assert store.get_case(case.id).outreach[0].status == OutreachStatus.drafted


def test_send_failure_leaves_drafted_and_does_not_raise(new_case, store, now):
    case = _stalled_case(new_case, store, now, 5, auto_send_rungs=[Rung.nudge])
    provider = FailingProvider()

    # The tick returns normally despite the provider failing.
    drafted = _bene(api.run_scheduler(store, now=now, provider=provider))

    assert len(drafted) == 1
    assert len(provider.calls) == 1  # a send was attempted
    persisted = store.get_case(case.id).outreach[0]
    assert persisted.status == OutreachStatus.drafted  # falls back to the queue
    assert persisted.sent_via is None
    assert persisted.message_id is None


def test_no_provider_drafts_only(new_case, store, now):
    # Without a provider the scheduler only drafts (phase-1 behavior), even when
    # auto_send_rungs is populated.
    case = _stalled_case(new_case, store, now, 5, auto_send_rungs=[Rung.nudge])

    drafted = _bene(api.run_scheduler(store, now=now))

    assert len(drafted) == 1
    persisted = store.get_case(case.id).outreach[0]
    assert persisted.status == OutreachStatus.drafted
    assert persisted.sent_via is None
