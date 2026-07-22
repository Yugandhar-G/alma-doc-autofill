"""Listener tests — filtering, all-null ask-for-fields, happy-path case creation."""

from __future__ import annotations

from core.events import query_events
from slack_agent import listener
from slack_agent.listener import handle_handoff_message

from tests.slack_agent.conftest import ALL_NULL, RAVI_MEI, make_parser


# -- should_handle filter --------------------------------------------------- #

def test_should_handle_accepts_top_level_human_post():
    event = {"channel": "C1", "ts": "1.0", "text": "New case"}
    assert listener.should_handle(event, "C1") is True


def test_should_handle_rejects_other_channel():
    assert listener.should_handle({"channel": "C2", "ts": "1.0", "text": "x"}, "C1") is False


def test_should_handle_rejects_bot_and_thread_reply():
    assert listener.should_handle({"channel": "C1", "ts": "1.0", "text": "x", "bot_id": "B"}, "C1") is False
    assert listener.should_handle({"channel": "C1", "ts": "2.0", "thread_ts": "1.0", "text": "x"}, "C1") is False


# -- all-null parse: nothing invented --------------------------------------- #

def test_all_null_parse_asks_and_creates_nothing(db, slack, run):
    case_id = run(
        handle_handoff_message(
            conn=db,
            client=slack,
            channel="C1",
            message_ts="100.1",
            text="something unparseable",
            parse=make_parser(ALL_NULL),
        )
    )
    assert case_id is None
    # Reply posted in-thread asking for the fields.
    assert len(slack.posts) == 1
    assert slack.posts[0]["thread_ts"] == "100.1"
    # NOTHING invented: no case / client / party / intake / event rows.
    assert db.execute('SELECT COUNT(*) FROM "case"').fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM client").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM intake").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM event").fetchone()[0] == 0


# -- happy path ------------------------------------------------------------- #

def test_handoff_creates_case_parties_intakes_and_event(db, slack, run):
    case_id = run(
        handle_handoff_message(
            conn=db,
            client=slack,
            channel="C1",
            message_ts="200.2",
            text="New marriage case ...",
            parse=make_parser(RAVI_MEI),
        )
    )
    assert case_id is not None

    assert db.execute('SELECT COUNT(*) FROM "case"').fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM client").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM party WHERE case_id = ?", (case_id,)).fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM intake WHERE case_id = ?", (case_id,)).fetchone()[0] == 2

    # Intakes start 'sent' (§1.3).
    states = {r["state"] for r in db.execute("SELECT state FROM intake WHERE case_id = ?", (case_id,))}
    assert states == {"sent"}

    events = query_events(db, case_id=case_id)
    assert [e.type for e in events] == ["case.handoff_received"]
    # Payload carries counts only — no PII.
    assert events[0].payload["parties"] == 2
    assert events[0].payload["process_type_known"] is True

    # Thread reply posted with the missing-phone asks (phones were null).
    assert slack.posts[0]["thread_ts"] == "200.2"


def test_handoff_missing_phone_is_asked_not_invented(db, slack, run):
    run(
        handle_handoff_message(
            conn=db,
            client=slack,
            channel="C1",
            message_ts="9.9",
            text="...",
            parse=make_parser(RAVI_MEI),
        )
    )
    # Phones were null in the parse — stored null, never guessed.
    phones = [r["phone"] for r in db.execute("SELECT phone FROM client")]
    assert phones == [None, None]
