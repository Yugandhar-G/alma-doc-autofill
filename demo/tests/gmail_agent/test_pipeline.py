"""pipeline — email.received masking + ordering, draft kind, unmatched case id."""

from __future__ import annotations

import json

from core import drafts
from core.events import query_events
from gmail_agent import config, pipeline
from gmail_agent.parsing import InboundEmail
from gmail_agent.pipeline import EmailDecision


def _inbound(**over) -> InboundEmail:
    base = dict(
        gmail_message_id="m1",
        gmail_thread_id="t1",
        rfc_message_id="<orig@mail>",
        from_name="Ravi",
        from_address="ravi@demo.test",
        subject="hello",
        body="secret body text",
    )
    base.update(over)
    return InboundEmail(**base)


def test_email_received_carries_no_raw_pii(db):
    inbound = _inbound(from_address="secret@demo.test", subject="hello", body="secret body text")
    decision = EmailDecision(
        category="other", reply_subject=None, reply_body=None, matched_case_id=None
    )
    pipeline.process(db, inbound, decision)

    events = query_events(db, type="email.received")
    assert len(events) == 1
    payload = events[0].payload
    blob = json.dumps(payload)
    assert "secret@demo.test" not in blob
    assert "secret body text" not in blob
    assert len(payload["from_hash"]) == 64
    assert payload["subject_len"] == len("hello")
    assert payload["category"] == "other"


def test_no_draft_when_no_reply_body(db):
    decision = EmailDecision(
        category="no_action", reply_subject=None, reply_body=None, matched_case_id=None
    )
    result = pipeline.process(db, _inbound(), decision)
    assert result.draft_id is None
    assert query_events(db, type="draft.created") == []


def test_status_question_maps_to_status_reply_kind(db):
    decision = EmailDecision(
        category="status_question",
        reply_subject="Update",
        reply_body="Here is your status.",
        matched_case_id="case_demo",
        missing_items=["W-2 forms"],
        case_state={"gmail_thread_id": "t1"},
    )
    result = pipeline.process(db, _inbound(), decision)
    draft = drafts.get_draft(db, result.draft_id)
    assert draft.kind == "status_reply"
    assert draft.grounding.missing_items == ["W-2 forms"]


def test_unmatched_sender_uses_placeholder_case_id(db):
    decision = EmailDecision(
        category="new_client",
        reply_subject="Thanks",
        reply_body="Thanks for reaching out.",
        matched_case_id=None,
    )
    result = pipeline.process(db, _inbound(), decision)
    draft = drafts.get_draft(db, result.draft_id)
    assert draft.kind == "client_email"
    assert draft.case_id == config.UNMATCHED_CASE_ID


def test_email_received_precedes_draft_created(db):
    decision = EmailDecision(
        category="status_question",
        reply_subject="Update",
        reply_body="Status.",
        matched_case_id="case_demo",
        case_state={},
    )
    pipeline.process(db, _inbound(), decision)
    types = [e.type for e in query_events(db)]
    assert types.index("email.received") < types.index("draft.created")
