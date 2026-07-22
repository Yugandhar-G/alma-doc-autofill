"""Escalation handler tests — send again / call client / pause chasing."""

from __future__ import annotations

from core.events import query_events
from slack_agent import escalations, threads
from seed import seed_case


def test_send_again_creates_pending_manual_draft_and_emits(db, slack, run):
    seed_case.seed(db)
    draft_id = run(
        escalations.send_again(
            db, slack, seed_case.CASE_ID, channel="C1", message_ts="5.0"
        )
    )
    row = db.execute("SELECT trigger, state FROM draft WHERE id = ?", (draft_id,)).fetchone()
    assert row["trigger"] == "manual"
    assert row["state"] == "pending"
    # draft.created emitted so it flows through the normal approval path.
    created = [e for e in query_events(db, type="draft.created") if e.payload.get("draft_id") == draft_id]
    assert created


def test_call_client_updates_message_only(db, slack, run):
    seed_case.seed(db)
    run(escalations.call_client(db, slack, seed_case.CASE_ID, channel="C1", message_ts="5.0"))
    assert slack.updates
    assert db.execute("SELECT COUNT(*) FROM draft").fetchone()[0] == 0


def test_pause_chasing_sets_flag(db, slack, run):
    seed_case.seed(db)
    run(escalations.pause_chasing(db, slack, seed_case.CASE_ID, channel="C1", message_ts="5.0"))
    assert threads.is_paused(db, seed_case.CASE_ID) is True


def test_post_escalation_falls_back_to_channel_when_unmapped(db, slack, run):
    seed_case.seed(db)
    from core.models import Event

    ev = Event(type="escalation.raised", case_id=seed_case.CASE_ID, actor="agent:followup", payload={})
    run(escalations.post_escalation(db, slack, ev, fallback_channel="C_CASES"))
    assert slack.posts[0]["channel"] == "C_CASES"
    assert slack.posts[0]["thread_ts"] is None
