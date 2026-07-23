"""Listener tests — the Bolt filter (unchanged) + delegation to the agent loop.

handle_handoff_message now delegates to handoff_agent.run_handoff with no model
argument, so these drive it through the None-model path: wire_agent installs the
fake loop and its scripted-model factory (the setter).
"""

from __future__ import annotations

from core.events import query_events
from slack_agent import listener
from slack_agent.listener import handle_handoff_message

_RAVI = "ravi.kumar.demo@example.com"
_MEI = "mei.lin.demo@example.com"
_PROCESS = "I-130 and I-485 One Step Marriage Based Green Cards"


def _both_parties_script():
    return [
        ("find_existing_client", {"email": _RAVI}),
        ("find_existing_client", {"email": _MEI}),
        (
            "create_case_record",
            {
                "process_type": _PROCESS,
                "case_name": "Ravi Kumar / Mei Lin",
                "parties": [
                    {"role": "petitioner", "first_name": "Ravi", "last_name": "Kumar", "email": _RAVI},
                    {"role": "beneficiary", "first_name": "Mei", "last_name": "Lin", "email": _MEI},
                ],
            },
        ),
    ]


# -- should_handle filter (unchanged behavior) ------------------------------ #

def test_should_handle_accepts_top_level_human_post():
    event = {"channel": "C1", "ts": "1.0", "text": "New case"}
    assert listener.should_handle(event, "C1") is True


def test_should_handle_rejects_other_channel():
    assert listener.should_handle({"channel": "C2", "ts": "1.0", "text": "x"}, "C1") is False


def test_should_handle_rejects_bot_and_thread_reply():
    assert listener.should_handle({"channel": "C1", "ts": "1.0", "text": "x", "bot_id": "B"}, "C1") is False
    assert listener.should_handle({"channel": "C1", "ts": "2.0", "thread_ts": "1.0", "text": "x"}, "C1") is False


def test_should_handle_rejects_mention_of_bot():
    event = {"channel": "C1", "ts": "1.0", "text": "<@U123> look at this"}
    assert listener.should_handle(event, "C1", bot_user_id="U123") is False


# -- unparseable: nothing invented ------------------------------------------ #

def test_unparseable_asks_and_creates_nothing(db, slack, run, wire_agent):
    wire_agent([("ask_in_thread", {"questions": ["Who are the parties?"]})])
    case_id = run(
        handle_handoff_message(
            conn=db, client=slack, channel="C1", message_ts="100.1",
            text="something unparseable",
        )
    )
    assert case_id is None
    assert len(slack.posts) == 1
    assert slack.posts[0]["thread_ts"] == "100.1"
    assert db.execute('SELECT COUNT(*) FROM "case"').fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM client").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM intake").fetchone()[0] == 0
    assert query_events(db, type="case.handoff_received") == []


# -- happy path ------------------------------------------------------------- #

def test_handoff_creates_case_parties_intakes_and_event(db, slack, run, wire_agent):
    wire_agent(_both_parties_script())
    case_id = run(
        handle_handoff_message(
            conn=db, client=slack, channel="C1", message_ts="200.2",
            text="New marriage case ...",
        )
    )
    assert case_id is not None

    assert db.execute('SELECT COUNT(*) FROM "case"').fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM client").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM party WHERE case_id = ?", (case_id,)).fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM intake WHERE case_id = ?", (case_id,)).fetchone()[0] == 2

    states = {r["state"] for r in db.execute("SELECT state FROM intake WHERE case_id = ?", (case_id,))}
    assert states == {"sent"}

    # casewrite now opens a case-history stub per party (each emits
    # case_history.updated) before handoff_agent emits case.handoff_received.
    events = query_events(db, case_id=case_id)
    assert [e.type for e in events] == [
        "case_history.updated",
        "case_history.updated",
        "case.handoff_received",
    ]
    handoff = query_events(db, type="case.handoff_received")[0]
    assert handoff.payload["parties"] == 2  # real party count, not line count
    assert handoff.payload["process_type_known"] is True

    assert slack.posts[0]["thread_ts"] == "200.2"


def test_handoff_missing_phone_is_asked_not_invented(db, slack, run, wire_agent):
    wire_agent(_both_parties_script())  # phones omitted in the script
    run(
        handle_handoff_message(
            conn=db, client=slack, channel="C1", message_ts="9.9", text="...",
        )
    )
    phones = [r["phone"] for r in db.execute("SELECT phone FROM client")]
    assert phones == [None, None]


def test_handoff_creates_case_history_stubs_with_shared_case_number(db, slack, run, wire_agent):
    """Round-trip through the canned parser (wire_agent + ScriptModel from
    conftest): case created -> 2 case-history stubs -> one shared firm case
    number -> the number shows as a captured line in the Slack reply.

    BLOCKED on core.case_history (built in parallel) until it lands: casewrite
    now calls next_case_number + create_stub on every handoff."""
    import json

    from core.case_history import get_history

    wire_agent(_both_parties_script())
    case_id = run(
        handle_handoff_message(
            conn=db, client=slack, channel="C1", message_ts="300.3",
            text="New marriage case ...",
        )
    )
    assert case_id is not None

    records = get_history(db, case_id)
    assert {r.role for r in records} == {"petitioner", "beneficiary"}
    numbers = {r.case_number for r in records}
    assert len(numbers) == 1  # one shared case number across both stubs
    number = numbers.pop()
    assert number.startswith("YIL-")

    reply = json.dumps([p.get("blocks") for p in slack.posts])
    assert f"Case number: {number}" in reply


# --- @yunaki-only routing: handoff vs question discrimination (Jul 22) ---
from slack_agent.listener import looks_like_handoff


def test_looks_like_handoff_true_on_client_email():
    assert looks_like_handoff("New marriage case, Ravi ravi@x.com, Mei mei@y.com")


def test_looks_like_handoff_true_on_keywords():
    assert looks_like_handoff("open a case for a new client")
    assert looks_like_handoff("petitioner and beneficiary details attached")


def test_looks_like_handoff_false_on_question():
    assert not looks_like_handoff("what is the status of case 156?")
    assert not looks_like_handoff("share schema1 reply")
    assert not looks_like_handoff("look at the case we are working on")
