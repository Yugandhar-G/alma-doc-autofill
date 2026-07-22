"""email_agent — the REAL bounded loop, exercised with a scripted fake loop.

Required cases (directive): agent that found 3 missing items via tools drafts
them ⇒ draft has exactly those labels; a reply naming an item NOT in the
transcript is audited down to no_action; a terminal no_action ⇒ event only; a
budget exhaustion ⇒ no_action + loud log.
"""

from __future__ import annotations

import logging

from agents import harness
from core import drafts
from core.events import query_events
from gmail_agent import email_agent, pipeline
from gmail_agent.parsing import InboundEmail
from tests.gmail_agent.conftest import ScriptModel, seed_case_with_items

_LABELS = ["W-2 forms", "Employment Verification letter", "Marriage certificate"]


def _inbound(email: str = "ravi@demo.test") -> InboundEmail:
    return InboundEmail(
        gmail_message_id="m1",
        gmail_thread_id="t1",
        rfc_message_id="<orig@mail>",
        from_name="Ravi",
        from_address=email,
        subject="Any update?",
        body="Hi, can you tell me what documents you still need from me?",
    )


def test_agent_drafts_exactly_the_surfaced_missing_items(db, wire_agent, run):
    seed_case_with_items(db, email="ravi@demo.test", labels=_LABELS)
    script = [
        ("lookup_client_by_email", {"email": "ravi@demo.test"}),
        ("get_case_snapshot", {"case_id": "case_demo"}),
        ("list_checklist_items", {"intake_id": "intake_demo", "missing_only": True}),
        (
            "create_reply_draft",
            {
                "category": "status_question",
                "reply_subject": "Documents still needed",
                "reply_body": (
                    "Hi Ravi, we still need: W-2 forms, "
                    "Employment Verification letter, Marriage certificate."
                ),
            },
        ),
    ]
    decision = run(
        email_agent.run_email_agent(db, _inbound(), model=ScriptModel(script))
    )
    assert decision.category == "status_question"
    assert decision.reply_body is not None
    assert set(decision.missing_items) == set(_LABELS)
    assert decision.matched_case_id == "case_demo"

    result = pipeline.process(db, _inbound(), decision)
    draft = drafts.get_draft(db, result.draft_id)
    assert draft.kind == "status_reply"
    assert set(draft.grounding.missing_items) == set(_LABELS)
    # transcript persisted
    row = db.execute("SELECT COUNT(*) c FROM agent_transcript").fetchone()
    assert row["c"] == 1


def test_reply_naming_unseen_item_audited_to_no_action(db, wire_agent, run):
    seed_case_with_items(db, email="ravi@demo.test", labels=_LABELS)
    # The agent never lists checklist items (nothing surfaced), yet names one.
    script = [
        ("lookup_client_by_email", {"email": "ravi@demo.test"}),
        (
            "create_reply_draft",
            {
                "category": "status_question",
                "reply_subject": "Docs",
                "reply_body": "You still need the Marriage certificate.",
            },
        ),
    ]
    decision = run(
        email_agent.run_email_agent(db, _inbound(), model=ScriptModel(script))
    )
    assert decision.category == "no_action"
    assert decision.reply_body is None
    assert decision.case_state.get("no_action_reason") == "grounding_violation"


def test_terminal_no_action_event_only(db, wire_agent, run):
    script = [
        ("lookup_client_by_email", {"email": "stranger@demo.test"}),
        ("no_action", {"reason": "newsletter"}),
    ]
    decision = run(
        email_agent.run_email_agent(db, _inbound("stranger@demo.test"), model=ScriptModel(script))
    )
    assert decision.category == "no_action"
    assert decision.reply_body is None

    result = pipeline.process(db, _inbound("stranger@demo.test"), decision)
    assert result.draft_id is None
    assert len(query_events(db, type="email.received")) == 1
    assert query_events(db, type="draft.created") == []


def test_budget_exhaustion_yields_no_action_and_loud_log(db, wire_agent, run, caplog):
    seed_case_with_items(db, email="ravi@demo.test", labels=_LABELS)
    harness.MAX_TOOL_CALLS = 2  # restored by the db fixture
    # Two reads exhaust the budget before the terminal call is ever dispatched.
    script = [
        ("lookup_client_by_email", {"email": "ravi@demo.test"}),
        ("get_case_snapshot", {"case_id": "case_demo"}),
        (
            "create_reply_draft",
            {"category": "status_question", "reply_subject": "x", "reply_body": "y"},
        ),
    ]
    with caplog.at_level(logging.WARNING, logger="gmail_agent.email_agent"):
        decision = run(
            email_agent.run_email_agent(db, _inbound(), model=ScriptModel(script))
        )
    assert decision.category == "no_action"
    assert decision.reply_body is None
    assert any("NO terminal decision" in rec.message for rec in caplog.records)
