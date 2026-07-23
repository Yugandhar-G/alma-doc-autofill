"""Case-history lifecycle end-to-end (workplan §5 trust-but-verify).

ONE offline chain across the three layers that landed in parallel:

  1. Handoff (established offline path: canned parser + scripted kernel loop,
     conftest's `wire_agent`) opens a case, plants two case-history stubs
     (petitioner + beneficiary) under ONE shared firm case number.
  2. Nanda's form-submit path (`core.case_history.upsert_history`) overwrites the
     beneficiary stub with a fuller BeneficiaryHistory — same row, case_number
     preserved, updated_at bumped, PII-free `case_history.updated` on the bus.
  3. @yunaki reads it: the mention agent (scripted Claude model, real
     `get_case_history` tool) answers, and the tool the model saw is verified by
     invoking it directly.
  4. Nothing is ever sent: `message_sent` stays empty and the event log carries
     only case-history + handoff types — never a send-shaped event.

Reuses the fictional cast from the handoff (Ravi Kumar / Mei Lin). Invents no
new names. No network, no Gemini, no Anthropic — the handoff loop is scripted
(conftest) and the mention loop runs a FakeMessagesListChatModel.
"""

from __future__ import annotations

import json
import sqlite3
import time

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from core import events
from core.case_history import (
    BeneficiaryHistory,
    CaseHistoryRecord,
    EmploymentEntry,
    ImmigrationHistory,
    MarriageEntry,
    PersonName,
    get_history,
    upsert_history,
)
from slack_agent import mention
from slack_agent.agent_tools import ToolDeps, build_agent_tools
from slack_agent.deep_agent import AgentBudget, AgentRun
from slack_agent.listener import handle_handoff_message

BOT = "U0YUNAKI"

_RAVI = "ravi.kumar.demo@example.com"
_MEI = "mei.lin.demo@example.com"
_PROCESS = "I-130 and I-485 One Step Marriage Based Green Cards"
_CHANNEL = "C1"

# Reused verbatim from the handoff cast — no new names invented anywhere here.
_PII_STRINGS = ("Ravi", "Kumar", "Mei", "Lin", _RAVI, _MEI)

# A distinctive value planted in the beneficiary's immigration block so we can
# prove the upserted data reaches the rendered immigration section.
_IMMIG_STATUS = "F-1 Student"
_IMMIG_ENTRY = "San Francisco, CA"

# Send-shaped event types that must NEVER appear in this decision-support flow.
_SEND_SHAPED = {
    "message.sent",
    "draft.created",
    "draft.approved",
    "draft.rejected",
}


# --------------------------------------------------------------------------- #
# Scripted mention model (test_mention pattern) + handoff script
# --------------------------------------------------------------------------- #

class ScriptedChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _tool_call_msg(*calls):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{i}"}
            for i, (name, args) in enumerate(calls)
        ],
    )


def _both_parties_script() -> list[tuple[str, dict]]:
    """Same canned handoff the listener tests use: two client lookups then the
    terminal create with both parties. Phones omitted -> null, never guessed."""
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


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _do_handoff(db, slack, run, wire_agent, *, message_ts: str) -> str:
    """Drive the established offline handoff path and return the new case_id."""
    wire_agent(_both_parties_script())
    case_id = run(
        handle_handoff_message(
            conn=db, client=slack, channel=_CHANNEL, message_ts=message_ts,
            text="New marriage case, adjustment of status. Ravi + spouse Mei",
        )
    )
    assert case_id is not None
    return case_id


def _fuller_beneficiary() -> BeneficiaryHistory:
    """Nanda's form submission for Mei Lin: immigration block + one employment
    entry + one marriage entry, built with the real models. Same cast as the
    handoff — no new names."""
    return BeneficiaryHistory(
        legal_name=PersonName(first="Mei", last="Lin"),
        email=_MEI,
        date_of_birth="1993-07-02",
        birth_city="Chengdu",
        birth_country="China",
        immigration=ImmigrationHistory(
            current_status=_IMMIG_STATUS,
            place_of_last_entry=_IMMIG_ENTRY,
            inspected_at_entry=True,
            i765_filed=True,
            prior_petition_filed=False,
            removal_proceedings=False,
            visa_denied=False,
        ),
        employment_history=[
            EmploymentEntry(
                employer_name="Golden Gate University",
                job_title="Research Assistant",
                from_date="2024-09-01",
                current=True,
            )
        ],
        marriage_history=[
            MarriageEntry(
                marriage_date="2025-11-08",
                marriage_city="San Jose",
                marriage_state="California",
                marriage_country="United States",
                current=True,
                spouse_name=PersonName(first="Ravi", last="Kumar"),
            )
        ],
    )


def _tools(db: sqlite3.Connection) -> dict:
    """Fresh grant set over the same DB — used to verify the exact tool output
    the scripted mention model saw."""
    run = AgentRun()
    return {t.name: t for t in build_agent_tools(ToolDeps(conn=db), run, AgentBudget())}


def _hist_payloads(db: sqlite3.Connection) -> list[dict]:
    return [e.payload for e in events.query_events(db, type="case_history.updated")]


# --------------------------------------------------------------------------- #
# 1) The full lifecycle: handoff -> upsert -> read -> nothing sent
# --------------------------------------------------------------------------- #

def test_case_history_lifecycle_overview(db, slack, run, wire_agent, monkeypatch):
    # -- Step 1: handoff plants two stubs under one shared firm case number --- #
    case_id = _do_handoff(db, slack, run, wire_agent, message_ts="300.3")

    records = get_history(db, case_id)
    assert {r.role for r in records} == {"petitioner", "beneficiary"}
    numbers = {r.case_number for r in records}
    assert len(numbers) == 1
    case_number = numbers.pop()
    assert case_number.startswith("YIL-")

    by_role = {r.role: r for r in records}
    beneficiary_stub = by_role["beneficiary"]
    # Identity basics present from the stub; everything else is honest absence.
    assert beneficiary_stub.beneficiary.legal_name.first == "Mei"
    assert beneficiary_stub.beneficiary.email == _MEI
    assert beneficiary_stub.beneficiary.immigration is None
    assert beneficiary_stub.uscis_case_number is None
    assert beneficiary_stub.case_status is None
    stub_created_at = beneficiary_stub.created_at
    stub_updated_at = beneficiary_stub.updated_at

    hist_events_after_handoff = len(_hist_payloads(db))
    assert hist_events_after_handoff == 2  # one stub-open event per party

    # -- Step 2: Nanda's form submission overwrites the beneficiary stub ------ #
    # case_number intentionally None on the incoming record: the store must
    # PRESERVE the firm number via COALESCE, not blank it.
    time.sleep(0.01)  # guarantee a strictly later updated_at (microsecond ISO)
    incoming = CaseHistoryRecord(
        case_id=case_id,
        role="beneficiary",
        case_number=None,
        beneficiary=_fuller_beneficiary(),
    )
    stored = upsert_history(db, incoming, actor="agent:validation")

    # Same two rows — an overwrite, never a duplicate.
    records_after = get_history(db, case_id)
    assert len(records_after) == 2
    assert {r.role for r in records_after} == {"petitioner", "beneficiary"}

    # case_number preserved, created_at preserved, updated_at bumped.
    assert stored.case_number == case_number
    assert stored.created_at == stub_created_at
    assert stored.updated_at > stub_updated_at
    # The fuller payload actually landed.
    assert stored.beneficiary.immigration.current_status == _IMMIG_STATUS
    assert stored.beneficiary.employment_history[0].employer_name == "Golden Gate University"

    # A third case_history.updated fired, and EVERY such payload is PII-free.
    payloads = _hist_payloads(db)
    assert len(payloads) == hist_events_after_handoff + 1
    for payload in payloads:
        blob = json.dumps(payload)
        for needle in (*_PII_STRINGS, _IMMIG_STATUS, _IMMIG_ENTRY):
            assert needle not in blob, f"PII {needle!r} leaked onto the event bus: {blob}"
        # Only the documented, aggregate keys ride the bus.
        assert set(payload) == {"role", "fields_present", "has_uscis_number", "has_case_status"}

    # -- Step 3: @yunaki reads it (scripted model), verified against the tool -- #
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    model = ScriptedChatModel(
        responses=[
            _tool_call_msg(("get_case_history", {"case_query": "Kumar"})),
            AIMessage(content="Here's the case-history overview you asked for."),
        ]
    )
    reply = run(
        mention.handle_mention(
            conn=db, client=slack, channel=_CHANNEL, message_ts="9.0",
            thread_ts="300.3",  # inside the handoff thread -> case-scoped
            text=f"<@{BOT}> pull up the case history",
            model_factory=lambda: model,
        )
    )
    assert reply == "Here's the case-history overview you asked for."
    assert slack.posts[-1]["thread_ts"] == "300.3"

    # Verify the exact observation the model saw by invoking the tool directly.
    overview = run(_tools(db)["get_case_history"].coroutine(case_query="Kumar"))
    assert f"Case number: {case_number}" in overview
    assert "USCIS case number: not on file" in overview  # never estimated
    assert "Case status: not on file" in overview
    assert len(overview) <= 4000

    # -- Step 4: nothing sent, and no send-shaped event anywhere -------------- #
    assert db.execute("SELECT COUNT(*) c FROM message_sent").fetchone()["c"] == 0
    all_types = {e.type for e in events.query_events(db)}
    assert all_types == {"case_history.updated", "case.handoff_received"}
    assert all_types.isdisjoint(_SEND_SHAPED)


# --------------------------------------------------------------------------- #
# 2) The immigration section: model reads it, tool proves the slice
# --------------------------------------------------------------------------- #

def test_case_history_lifecycle_immigration_section(db, slack, run, wire_agent, monkeypatch):
    case_id = _do_handoff(db, slack, run, wire_agent, message_ts="400.4")
    case_number = get_history(db, case_id)[0].case_number

    upsert_history(
        db,
        CaseHistoryRecord(
            case_id=case_id, role="beneficiary", case_number=None,
            beneficiary=_fuller_beneficiary(),
        ),
        actor="agent:validation",
    )

    # Scripted model drills into the immigration section.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    model = ScriptedChatModel(
        responses=[
            _tool_call_msg(("get_case_history", {"case_query": "Kumar", "section": "immigration"})),
            AIMessage(content="Beneficiary is in F-1 status; petitioner has no immigration record."),
        ]
    )
    reply = run(
        mention.handle_mention(
            conn=db, client=slack, channel=_CHANNEL, message_ts="9.1",
            thread_ts="400.4",
            text=f"<@{BOT}> what's the immigration history?",
            model_factory=lambda: model,
        )
    )
    assert reply is not None
    assert slack.posts[-1]["thread_ts"] == "400.4"

    # Verify the tool slice the model consumed.
    section = run(
        _tools(db)["get_case_history"].coroutine(case_query="Kumar", section="immigration")
    )
    # Upserted beneficiary immigration data is rendered.
    assert _IMMIG_STATUS in section
    assert _IMMIG_ENTRY in section
    # Immigration is not a petitioner concept — reported as such, never guessed.
    assert "not applicable to the petitioner record" in section
    # Fields the beneficiary never answered stay "not on file".
    assert "not on file" in section
    assert len(section) <= 4000

    # Firm case number still intact after the fuller upsert.
    assert case_number.startswith("YIL-")
    assert get_history(db, case_id, "beneficiary")[0].case_number == case_number

    # Still zero sends, still only the two benign event types.
    assert db.execute("SELECT COUNT(*) c FROM message_sent").fetchone()["c"] == 0
    assert {e.type for e in events.query_events(db)} == {
        "case_history.updated",
        "case.handoff_received",
    }
