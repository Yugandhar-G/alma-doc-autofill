"""Approval flow tests — approve/reject/edit through the sendgate."""

from __future__ import annotations

from core import drafts
from core.events import query_events
from core.models import DraftAction, DraftGrounding, DraftTo
from slack_agent import approvals, senders, threads


def _make_draft(db) -> DraftAction:
    draft = DraftAction(
        case_id="case_x",
        kind="client_email",
        trigger="followup_timer",
        to=DraftTo(name="Ravi Kumar", channel_address="ravi.kumar.demo@example.com"),
        subject="Docs needed",
        body="Hi Ravi, we still need a few documents.",
        grounding=DraftGrounding(missing_items=["W-2s"], days_since_activity=4),
    )
    return drafts.create_draft(db, draft)


def test_post_approval_falls_back_to_channel_when_unmapped(db, slack, run):
    draft = _make_draft(db)
    run(approvals.post_approval(db, slack, draft, fallback_channel="C_CASES"))
    assert slack.posts[0]["channel"] == "C_CASES"
    assert slack.posts[0]["thread_ts"] is None


def test_post_approval_uses_thread_mapping_when_present(db, slack, run):
    draft = _make_draft(db)
    threads.map_thread(db, "case_x", "C1", "42.0")
    run(approvals.post_approval(db, slack, draft, fallback_channel="C_CASES"))
    assert slack.posts[0]["channel"] == "C1"
    assert slack.posts[0]["thread_ts"] == "42.0"


def test_approve_marks_sent_mocked_and_emits_chain(db, slack, run, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "false")
    draft = _make_draft(db)
    result = run(approvals.approve(db, slack, draft.id, channel="C1", message_ts="7.0"))

    assert result["mocked"] is True
    assert drafts.get_draft(db, draft.id).state == "sent"
    types = [e.type for e in query_events(db, case_id="case_x")]
    assert types == ["draft.approved", "message.sent"]
    # Message updated to the approved state.
    assert slack.updates[0]["ts"] == "7.0"


def test_reject_emits_rejected_with_reason(db, slack, run):
    draft = _make_draft(db)
    run(approvals.submit_reject(db, slack, draft.id, "wrong client", channel="C1", message_ts="7.0"))
    assert drafts.get_draft(db, draft.id).state == "rejected"
    events = query_events(db, type="draft.rejected")
    assert events[0].payload["reason"] == "wrong client"


def test_edit_updates_body_and_keeps_pending(db, slack, run):
    draft = _make_draft(db)
    run(approvals.submit_edit(db, slack, draft.id, "New body text.", channel="C1", message_ts="7.0"))
    updated = drafts.get_draft(db, draft.id)
    assert updated.body == "New body text."
    assert updated.state == "pending"


def test_registered_sender_routes_via_sendgate_in_live_mode(db, slack, run, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "true")
    sent: list[str] = []
    senders.register_sender("client_email", lambda draft: sent.append(draft.id))
    draft = _make_draft(db)

    result = run(approvals.approve(db, slack, draft.id, channel="C1", message_ts="7.0"))

    # Registered sender was invoked through the sendgate; not mocked.
    assert sent == [draft.id]
    assert result["mocked"] is False


def test_no_registered_sender_uses_placeholder_path(db, slack, run, monkeypatch):
    # No sender registered for this kind — placeholder path still completes.
    monkeypatch.setenv("LIVE_MODE", "false")
    draft = _make_draft(db)
    result = run(approvals.approve(db, slack, draft.id, channel="C1", message_ts="7.0"))
    assert result["mocked"] is True
    assert drafts.get_draft(db, draft.id).state == "sent"


def test_edit_ignored_after_approval(db, slack, run, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "false")
    draft = _make_draft(db)
    run(approvals.approve(db, slack, draft.id, channel="C1", message_ts="7.0"))
    run(approvals.submit_edit(db, slack, draft.id, "sneaky edit", channel="C1", message_ts="7.0"))
    # Body unchanged — guarded UPDATE only touches pending drafts.
    assert drafts.get_draft(db, draft.id).body != "sneaky edit"
