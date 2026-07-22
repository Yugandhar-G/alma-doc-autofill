"""Approval flow tests — approve/reject/edit + the §2.8 ack/async latency contract.

approve() now acks immediately and offloads the real send to a background asyncio
task (§2.8), so it returns the Task. `approve_and_wait` (conftest) drives the
schedule + awaits the task on one loop for the behavior tests; the latency test
inspects the ordering between ack and the send explicitly.
"""

from __future__ import annotations

import asyncio
import json
import logging

from core import drafts
from core.events import query_events
from core.models import DraftAction, DraftGrounding, DraftTo
from slack_agent import approvals, senders, threads

from tests.slack_agent.conftest import approve_and_wait


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


def test_approve_marks_sent_mocked_and_emits_chain(db, slack, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "false")
    draft = _make_draft(db)
    result = approve_and_wait(db, slack, draft.id, channel="C1", message_ts="7.0")

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


def test_registered_sender_routes_via_sendgate_in_live_mode(db, slack, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "true")
    sent: list[str] = []
    senders.register_sender("client_email", lambda draft: sent.append(draft.id))
    draft = _make_draft(db)

    result = approve_and_wait(db, slack, draft.id, channel="C1", message_ts="7.0")

    # Registered sender was invoked through the sendgate; not mocked.
    assert sent == [draft.id]
    assert result["mocked"] is False


def test_no_registered_sender_uses_placeholder_path(db, slack, monkeypatch):
    # No sender registered for this kind — placeholder path still completes.
    monkeypatch.setenv("LIVE_MODE", "false")
    draft = _make_draft(db)
    result = approve_and_wait(db, slack, draft.id, channel="C1", message_ts="7.0")
    assert result["mocked"] is True
    assert drafts.get_draft(db, draft.id).state == "sent"


def test_edit_ignored_after_approval(db, slack, run, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "false")
    draft = _make_draft(db)
    approve_and_wait(db, slack, draft.id, channel="C1", message_ts="7.0")
    run(approvals.submit_edit(db, slack, draft.id, "sneaky edit", channel="C1", message_ts="7.0"))
    # Body unchanged — guarded UPDATE only touches pending drafts.
    assert drafts.get_draft(db, draft.id).body != "sneaky edit"


# --------------------------------------------------------------------------- #
# §2.8 latency contract: ack before work; async failure never silent
# --------------------------------------------------------------------------- #

def test_ack_recorded_before_send_executes(db, slack, monkeypatch):
    """ack() completes and approve() returns BEFORE the send runs; the Slack
    message is updated only after the send (proven with an order probe)."""
    monkeypatch.setenv("LIVE_MODE", "true")
    order: list[str] = []

    async def fake_ack() -> None:
        order.append("ack")

    senders.register_sender("client_email", lambda draft: order.append("send"))
    draft = _make_draft(db)

    async def scenario() -> None:
        task = await approvals.approve(
            db, slack, draft.id, channel="C1", message_ts="7.0", ack=fake_ack
        )
        # Ack has happened; the send work is scheduled but has NOT run yet.
        assert order == ["ack"]
        assert slack.updates == []
        await task

    asyncio.run(scenario())

    assert order == ["ack", "send"]  # send strictly after ack
    assert slack.updates and slack.updates[0]["ts"] == "7.0"
    assert drafts.get_draft(db, draft.id).state == "sent"


def test_async_task_failure_updates_message_and_logs_loud(db, slack, monkeypatch, caplog):
    """A failure inside the background task must surface: a visible Slack error
    line AND a loud log — never a swallowed exception (§2.8 defect class)."""
    monkeypatch.setenv("LIVE_MODE", "false")

    def boom(*_args, **_kwargs):
        raise RuntimeError("send transport down")

    monkeypatch.setattr(approvals.sendgate, "execute_draft", boom)
    draft = _make_draft(db)

    with caplog.at_level(logging.ERROR, logger="slack_agent.approvals"):
        result = approve_and_wait(db, slack, draft.id, channel="C1", message_ts="7.0")

    # The task returned an error marker rather than crashing silently.
    assert result["error"] == "RuntimeError"
    # Visible error line posted to the Slack message.
    assert slack.updates and slack.updates[0]["ts"] == "7.0"
    assert "Approval failed" in json.dumps(slack.updates)
    # Loud log.
    assert any("approval work FAILED" in rec.message for rec in caplog.records)
