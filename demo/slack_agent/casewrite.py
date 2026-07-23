"""Persist a parsed handoff into the /core case model — CLAUDE_WORKPLAN.md §2.

/core exposes no case-creation helper (§1.3 frames the case model as "shared
read, B writes"), but §2 item 2 explicitly directs Workstream A to create
case + party + client + intake rows on handoff. We do that by validating through
the frozen pydantic models (core.models) and inserting into the core-owned
tables — reading the schema, writing rows, never editing /core code. Every value
that the parser returned as null stays null (NULL OVER GUESS, §4.3); the caller
turns those nulls into explicit "reply with it" asks.

On handoff we also mint ONE firm case number (core.case_history.next_case_number)
per new case and open a case-history stub (core.case_history.create_stub) per
party, seeded with only the values the parse actually carried — a null stays a
null there too. The case number leads the captured summary so it surfaces in the
thread reply. Stub creation failure is loud (the exception propagates), never
swallowed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from core.models import Case, Client, Intake, Party
from slack_agent.handoff_agent import HandoffParse

_INITIAL_STAGE = "Handoff received — intake pending"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PartyRecord:
    role: str
    display_name: str
    missing: list[str]


@dataclass(frozen=True)
class HandoffResult:
    case: Case
    parties: list[PartyRecord]
    captured_lines: list[str]
    missing: list[str]
    case_number: str


def _display_name(first: str | None, last: str | None) -> str:
    parts = [p for p in (first, last) if p]
    return " ".join(parts) if parts else "(name not captured)"


def create_handoff_case(conn: sqlite3.Connection, parsed: HandoffParse) -> HandoffResult:
    """Insert case + clients + parties + intakes. Returns a summary for the reply.

    Intakes start in state 'sent' (§1.3). process_type falls back to "" when the
    parser found none — an empty string records absence, and the caller asks for
    it rather than inventing a visa type.
    """
    now = _now_iso()
    process_type = parsed.process_type or ""

    first_names = [p.first_name for p in parsed.parties if p.first_name]
    case_name = " / ".join(first_names) if first_names else "New case"

    case = Case(name=case_name, process_type=process_type, stage=_INITIAL_STAGE)
    conn.execute(
        'INSERT INTO "case" (id, name, process_type, stage, created_at) '
        "VALUES (?, ?, ?, ?, ?)",
        (case.id, case.name, case.process_type, case.stage, case.created_at),
    )

    # Lazy import breaks any import-time coupling to the case-history layer
    # (built in parallel) and keeps this module importable before it lands.
    from core import case_history

    # ONE firm case number per new case, shared by every party stub below.
    case_number = case_history.next_case_number(conn)

    party_records: list[PartyRecord] = []
    captured_lines: list[str] = []
    missing: list[str] = []

    if not process_type:
        missing.append("process type")

    for parsed_party in parsed.parties:
        client = Client(
            first_name=parsed_party.first_name or "",
            last_name=parsed_party.last_name or "",
            email=parsed_party.email,
            phone=parsed_party.phone,
        )
        party = Party(case_id=case.id, client_id=client.id, role=parsed_party.role)
        intake = Intake(
            case_id=case.id,
            client_id=client.id,
            url=f"https://intake.demo.local/i/placeholder",
            state="sent",
            sent_at=now,
            last_client_activity_at=None,
        )
        # url references its own id — patch after construction for a stable link.
        intake = intake.model_copy(
            update={"url": f"https://intake.demo.local/i/{intake.id}"}
        )

        conn.execute(
            "INSERT INTO client (id, first_name, last_name, email, phone, whatsapp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                client.id,
                client.first_name,
                client.last_name,
                client.email,
                client.phone,
                client.whatsapp,
            ),
        )
        conn.execute(
            "INSERT INTO party (case_id, client_id, role) VALUES (?, ?, ?)",
            (party.case_id, party.client_id, party.role),
        )
        conn.execute(
            "INSERT INTO intake "
            "(id, case_id, client_id, url, state, sent_at, last_client_activity_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                intake.id,
                intake.case_id,
                intake.client_id,
                intake.url,
                intake.state,
                intake.sent_at,
                intake.last_client_activity_at,
            ),
        )

        # Firm case-history stub for this party — idempotent per (case, role).
        # Values come straight from the parse: a None stays None (NULL OVER
        # GUESS). Failure here must be loud, so the exception propagates.
        case_history.create_stub(
            conn,
            case_id=case.id,
            role=parsed_party.role,
            first_name=parsed_party.first_name,
            last_name=parsed_party.last_name,
            email=parsed_party.email,
            phone=parsed_party.phone,
            case_number=case_number,
            actor="agent:slack",
        )

        display = _display_name(parsed_party.first_name, parsed_party.last_name)
        captured_lines.append(f"{parsed_party.role}: {display}")

        party_missing: list[str] = []
        if not parsed_party.last_name:
            party_missing.append("last name")
        if not parsed_party.email:
            party_missing.append("email")
        if not parsed_party.phone:
            party_missing.append("phone")
        party_records.append(
            PartyRecord(role=parsed_party.role, display_name=display, missing=party_missing)
        )
        for field in party_missing:
            missing.append(f"{display} {field}")

    conn.commit()
    # The firm case number leads the captured summary so the thread reply shows
    # it up top ("Case number: YIL-2026-NNNN"); it flows through the untouched
    # handoff_agent -> blocks.handoff_summary_blocks path as a captured line.
    captured_lines = [f"Case number: {case_number}", *captured_lines]
    return HandoffResult(
        case=case,
        parties=party_records,
        captured_lines=captured_lines,
        missing=missing,
        case_number=case_number,
    )
