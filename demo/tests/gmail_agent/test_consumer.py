"""consumer — notification→events, loop prevention, dedup, baseline.

The email brain is stubbed via the harness seams (fake loop + scripted-model
factory); the Gmail API is the FakeGmailService. No network.
"""

from __future__ import annotations

from core.events import query_events
from gmail_agent import consumer, state
from tests.gmail_agent.conftest import FakeGmailService, make_message

_HISTORY_ONE = {"history": [{"messagesAdded": [{"message": {"id": "m1"}}]}]}


def _service(from_header: str) -> FakeGmailService:
    msg = make_message("m1", "t1", from_header, "Status?", "Any update on my case?")
    return FakeGmailService(
        history_page=_HISTORY_ONE, messages={"m1": msg}, threads={"t1": {"messages": [msg]}}
    )


def _script() -> list[tuple[str, dict]]:
    return [
        ("lookup_client_by_email", {"email": "ravi@demo.test"}),
        ("list_checklist_items", {"intake_id": "intake_demo", "missing_only": True}),
        (
            "create_reply_draft",
            {
                "category": "status_question",
                "reply_subject": "Docs still needed",
                "reply_body": "Hi Ravi, we still need: W-2 forms.",
            },
        ),
    ]


def _seed(db) -> None:
    from tests.gmail_agent.conftest import seed_case_with_items

    seed_case_with_items(db, email="ravi@demo.test", labels=["W-2 forms"])


def test_notification_emits_email_received_and_draft_created(db, wire_agent, cfg):
    _seed(db)
    wire_agent(_script())
    state.set_high_water(db, 100)  # baseline established (by watch, normally)
    service = _service("Ravi Kumar <ravi@demo.test>")

    summary = consumer.process_notification(
        db, service, cfg, {"emailAddress": "ravi@demo.test", "historyId": 200}
    )
    assert summary.processed == 1 and summary.drafts == 1
    assert len(query_events(db, type="email.received")) == 1
    assert len(query_events(db, type="draft.created")) == 1
    assert state.get_high_water(db) == 200


def test_own_address_is_skipped_no_event_no_draft(db, wire_agent, cfg):
    wire_agent(_script())
    state.set_high_water(db, 100)
    service = _service(f"Agent <{cfg.address}>")  # message from our own mailbox

    summary = consumer.process_notification(
        db, service, cfg, {"emailAddress": cfg.address, "historyId": 200}
    )
    assert summary.skipped_own == 1
    assert summary.processed == 0
    assert query_events(db, type="email.received") == []
    assert query_events(db, type="draft.created") == []


def test_same_notification_twice_dedupes_to_one_draft(db, wire_agent, cfg):
    _seed(db)
    wire_agent(_script())
    state.set_high_water(db, 100)
    service = _service("Ravi Kumar <ravi@demo.test>")
    notification = {"emailAddress": "ravi@demo.test", "historyId": 200}

    first = consumer.process_notification(db, service, cfg, notification)
    second = consumer.process_notification(db, service, cfg, notification)

    assert first.drafts == 1
    assert second.duplicates == 1 and second.drafts == 0
    assert len(query_events(db, type="draft.created")) == 1
    assert len(query_events(db, type="email.received")) == 1


def test_first_notification_sets_baseline_and_processes_nothing(db, wire_agent, cfg):
    wire_agent(_script())
    service = _service("Ravi Kumar <ravi@demo.test>")
    summary = consumer.process_notification(
        db, service, cfg, {"emailAddress": "ravi@demo.test", "historyId": 500}
    )
    assert summary.baseline_set is True
    assert summary.considered == 0
    assert state.get_high_water(db) == 500
