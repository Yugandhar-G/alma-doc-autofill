"""handoff_agent tests — the REAL kernel loop, exercised with a scripted loop.

Required cases (directive):
(a) both parties ⇒ create_case_record terminal ⇒ case + 2 parties + 2 intakes,
    case.handoff_received emitted, thread reply lists the nulls;
(b) unparseable ⇒ ask_in_thread terminal ⇒ NO case row, no handoff event, ask reply;
(c) budget exhaustion ⇒ ask fallback + loud log, no case.
"""

from __future__ import annotations

import json
import logging

from core.events import query_events
from slack_agent import handoff_agent, threads

from tests.slack_agent.conftest import ScriptModel

_PROCESS = "I-130 and I-485 One Step Marriage Based Green Cards"
_RAVI = "ravi.kumar.demo@example.com"
_MEI = "mei.lin.demo@example.com"


def _blocks_text(posts: list[dict]) -> str:
    return json.dumps([p.get("blocks") for p in posts])


def _both_parties_script() -> list[tuple[str, dict]]:
    return [
        ("find_existing_client", {"email": _RAVI}),
        ("find_existing_client", {"email": _MEI}),
        (
            "create_case_record",
            {
                "process_type": _PROCESS,
                "case_name": "Ravi Kumar / Mei Lin",
                # phones intentionally omitted -> null (never guessed)
                "parties": [
                    {"role": "petitioner", "first_name": "Ravi", "last_name": "Kumar", "email": _RAVI},
                    {"role": "beneficiary", "first_name": "Mei", "last_name": "Lin", "email": _MEI},
                ],
            },
        ),
    ]


def test_both_parties_create_case_record_terminal(db, slack, run, wire_agent):
    case_id = run(
        handoff_agent.run_handoff(
            conn=db,
            client=slack,
            channel="C_CASES",
            message_ts="500.1",
            text="New marriage case, adjustment of status. Ravi + spouse Mei",
            model=ScriptModel(_both_parties_script()),
        )
    )
    assert case_id is not None

    # Real rows written by casewrite through the terminal tool.
    assert db.execute('SELECT COUNT(*) FROM "case"').fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM party WHERE case_id = ?", (case_id,)).fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM intake WHERE case_id = ?", (case_id,)).fetchone()[0] == 2
    states = {r["state"] for r in db.execute("SELECT state FROM intake WHERE case_id = ?", (case_id,))}
    assert states == {"sent"}

    # NULL OVER GUESS: phones absent from the message stay null.
    phones = [r["phone"] for r in db.execute("SELECT phone FROM client")]
    assert phones == [None, None]

    # case.handoff_received emitted (only because a case was created).
    events = query_events(db, type="case.handoff_received")
    assert len(events) == 1
    assert events[0].case_id == case_id
    assert events[0].payload["parties"] == 2  # real party count, not line count
    assert events[0].payload["process_type_known"] is True
    assert events[0].payload["missing_count"] >= 2  # both phones null

    # Thread reply posted in-thread, listing the null (phone) asks and the
    # assigned firm case number as a captured line.
    assert slack.posts[0]["thread_ts"] == "500.1"
    assert "phone" in _blocks_text(slack.posts)
    assert "Case number: YIL-" in _blocks_text(slack.posts)

    # Thread mapping stored + transcript persisted.
    assert threads.get_thread(db, case_id) == {"channel": "C_CASES", "thread_ts": "500.1"}
    assert db.execute("SELECT COUNT(*) FROM agent_transcript").fetchone()[0] == 1


def test_unparseable_asks_in_thread_and_creates_nothing(db, slack, run, wire_agent):
    script = [
        (
            "ask_in_thread",
            {"questions": ["What is the process type?", "Who are the parties (names + emails)?"]},
        )
    ]
    case_id = run(
        handoff_agent.run_handoff(
            conn=db,
            client=slack,
            channel="C_CASES",
            message_ts="600.2",
            text="hey can someone look at this when you get a sec",
            model=ScriptModel(script),
        )
    )
    assert case_id is None

    # Nothing invented: no case / client / party / intake / handoff event.
    assert db.execute('SELECT COUNT(*) FROM "case"').fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM client").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM intake").fetchone()[0] == 0
    assert query_events(db, type="case.handoff_received") == []

    # Ask reply posted in-thread, carrying the agent's own questions.
    assert slack.posts[0]["thread_ts"] == "600.2"
    assert "process type" in _blocks_text(slack.posts)
    # Transcript persisted even though nothing was created.
    assert db.execute("SELECT COUNT(*) FROM agent_transcript").fetchone()[0] == 1


def test_budget_exhaustion_falls_back_to_ask_with_loud_log(db, slack, run, wire_agent, caplog):
    from agents import harness

    harness.MAX_TOOL_CALLS = 2  # restored by the db fixture
    # Two reads exhaust the budget before the terminal create is ever dispatched.
    with caplog.at_level(logging.WARNING, logger="slack_agent.handoff_agent"):
        case_id = run(
            handoff_agent.run_handoff(
                conn=db,
                client=slack,
                channel="C_CASES",
                message_ts="700.3",
                text="New marriage case, adjustment of status. Ravi + spouse Mei",
                model=ScriptModel(_both_parties_script()),
            )
        )
    assert case_id is None
    # No guessed case despite a create being scripted but never reached.
    assert db.execute('SELECT COUNT(*) FROM "case"').fetchone()[0] == 0
    assert query_events(db, type="case.handoff_received") == []
    # Loud, not silent.
    assert any("NO terminal decision" in rec.message for rec in caplog.records)
    # Still asks the human in-thread.
    assert slack.posts[0]["thread_ts"] == "700.3"


def test_find_existing_client_matches_seeded_client(db, slack, run, wire_agent):
    # Seed a client so the agent's first lookup returns matched=True.
    db.execute(
        "INSERT INTO client (id, first_name, last_name, email, phone, whatsapp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("client_seed", "Ravi", "Kumar", _RAVI, None, None),
    )
    db.commit()
    script = [
        ("find_existing_client", {"email": _RAVI}),
        (
            "create_case_record",
            {
                "process_type": _PROCESS,
                "case_name": None,
                "parties": [
                    {"role": "petitioner", "first_name": "Ravi", "last_name": "Kumar", "email": _RAVI}
                ],
            },
        ),
    ]
    case_id = run(
        handoff_agent.run_handoff(
            conn=db,
            client=slack,
            channel="C_CASES",
            message_ts="800.4",
            text="New case for Ravi",
            model=ScriptModel(script),
        )
    )
    assert case_id is not None
    # The lookup ran and recorded its outcome into the transcript log.
    row = db.execute("SELECT transcript_json FROM agent_transcript").fetchone()
    assert "find_existing_client -> matched a client on file" in row["transcript_json"]
