"""DoD integration — the full demo chain, scripted (CLAUDE_WORKPLAN.md §2 DoD).

Simulated handoff message ⇒ case + parties + intakes exist ⇒ (fake Workstream B)
emits draft.created ⇒ approval block posted in the case thread ⇒ simulated Approve
⇒ draft approved + sent (mocked) ⇒ event log shows the full chain:

    case.handoff_received → draft.created → draft.approved → message.sent
"""

from __future__ import annotations

from core import drafts
from core.events import emit, query_events
from core.models import DraftAction, DraftGrounding, DraftTo, Event
from slack_agent import approvals, listener
from slack_agent.router import EventRouter

from tests.slack_agent.conftest import RAVI_MEI, make_parser


def test_full_dod_chain(db, slack, run, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "false")

    # 1. Simulated handoff message → case + parties + intakes.
    case_id = run(
        listener.handle_handoff_message(
            conn=db,
            client=slack,
            channel="C_CASES",
            message_ts="1000.1",
            text="New marriage case, adjustment of status. Ravi + spouse Mei",
            parse=make_parser(RAVI_MEI),
        )
    )
    assert case_id is not None
    assert db.execute("SELECT COUNT(*) FROM party WHERE case_id = ?", (case_id,)).fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM intake WHERE case_id = ?", (case_id,)).fetchone()[0] == 2

    # 2. Fake Workstream B (a separate process in reality) creates a nudge draft
    #    and emits draft.created. Here we create + emit directly.
    draft = drafts.create_draft(
        db,
        DraftAction(
            case_id=case_id,
            kind="client_email",
            trigger="followup_timer",
            to=DraftTo(name="Ravi Kumar", channel_address="ravi.kumar.demo@example.com"),
            subject="A few documents still needed",
            body="Hi Ravi, we still need a few documents.",
            grounding=DraftGrounding(
                missing_items=["Employment Verification letter"], days_since_activity=4
            ),
        ),
    )
    emit(
        db,
        Event(
            type="draft.created",
            case_id=case_id,
            actor="agent:validation",
            payload={"draft_id": draft.id, "kind": draft.kind, "channel": draft.kind},
        ),
    )

    # 3. Router picks up draft.created via the poller (cross-process seam) and
    #    posts the approval block into the case's thread.
    async def on_draft_created(event: Event) -> None:
        d = drafts.get_draft(db, event.payload["draft_id"])
        await approvals.post_approval(db, slack, d, fallback_channel="C_CASES")

    router = EventRouter(db, {"draft.created": on_draft_created})
    router.poll_once()

    async def drain() -> None:
        while not router.queue.empty():
            await router.dispatch(router.queue.get_nowait())

    run(drain())

    # Approval posted into the handoff thread (mapping resolved).
    approval_posts = [p for p in slack.posts if p.get("thread_ts") == "1000.1"]
    assert approval_posts, "approval block should land in the case thread"

    # 4. Simulated Approve action.
    result = run(approvals.approve(db, slack, draft.id, channel="C_CASES", message_ts="1001.0"))
    assert result["mocked"] is True
    assert drafts.get_draft(db, draft.id).state == "sent"

    # 5. Event log shows the full DoD chain in order.
    chain = [e.type for e in query_events(db, case_id=case_id)]
    assert chain == [
        "case.handoff_received",
        "draft.created",
        "draft.approved",
        "message.sent",
    ]

    # Guardrail: no message.sent without a preceding draft.approved (§4.2).
    assert chain.index("draft.approved") < chain.index("message.sent")
