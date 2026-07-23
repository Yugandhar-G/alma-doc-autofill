"""Staff-created cases join the shared /core plane — the reverse of the
handoff consumer.

The HandoffConsumer covers Slack-first cases (core case exists, intake case
is created to match). This module covers intake-first cases: when staff
create a case in the web UI, mirror it into /core — case + clients + parties
+ intakes + case_history stubs + a firm case number — and record the id
mapping, so @yunaki, the event shim, history sync, and the sendgate email
lookup all work identically regardless of which door the case came in.

Loop safety with the consumer: we emit `case.handoff_received` (honest audit
of "a case arrived", actor human:staff) AFTER map_case — the consumer skips
any event whose core case is already mapped.

Same discipline as everything else in this package: never raises into the
caller's flow (the web hook wraps us in try/except), null over guess (a
single-token name yields first name only), no PII in logs.
"""

from __future__ import annotations

import logging
from typing import Any

from intake_workflow.integration import config

logger = logging.getLogger("intake_workflow.integration.case_link")


def _split_name(full: str | None) -> tuple[str | None, str | None]:
    parts = (full or "").strip().split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def link_staff_case(store_case: Any) -> str | None:
    """Mirror a staff-created intake case into /core. Returns the core case id
    (None when integration is disabled). Idempotent per intake case."""
    if not config.enabled():
        return None

    from core import case_history, events
    from core.models import Case, Client, Event, Intake, Party

    with config.shared_conn() as conn:
        existing = config.core_case_for(conn, store_case.id)
        if existing:
            return existing

        case = Case(
            name=store_case.title,
            process_type=store_case.case_type,
            stage="USCIS-Case Opened (client's information/checklist pending)",
        )
        conn.execute(
            'INSERT INTO "case" (id, name, process_type, stage, created_at) '
            "VALUES (?, ?, ?, ?, ?)",
            (case.id, case.name, case.process_type, case.stage, case.created_at),
        )

        case_number = case_history.next_case_number(conn)
        for party in store_case.parties:
            first, last = _split_name(party.full_name)
            client = Client(first_name=first or "", last_name=last or "",
                            email=party.email or None)
            conn.execute(
                "INSERT INTO client (id, first_name, last_name, email, phone, whatsapp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (client.id, client.first_name, client.last_name,
                 client.email, client.phone, client.whatsapp),
            )
            role = party.role.value if hasattr(party.role, "value") else str(party.role)
            p = Party(case_id=case.id, client_id=client.id, role=role)
            conn.execute(
                "INSERT INTO party (case_id, client_id, role) VALUES (?, ?, ?)",
                (p.case_id, p.client_id, p.role),
            )
            intake = Intake(
                case_id=case.id, client_id=client.id,
                url=f"{config.portal_base()}/c/{party.token}", state="sent",
            )
            conn.execute(
                "INSERT INTO intake (id, case_id, client_id, url, state, sent_at, "
                "last_client_activity_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (intake.id, intake.case_id, intake.client_id, intake.url,
                 intake.state, intake.sent_at, intake.last_client_activity_at),
            )
            case_history.create_stub(
                conn, case_id=case.id, role=role,
                first_name=first, last_name=last,
                email=party.email or None, phone=None,
                case_number=case_number, actor="human:staff",
            )
        conn.commit()

        config.map_case(conn, store_case.id, case.id)
        events.emit(conn, Event(
            type="case.handoff_received", case_id=case.id, actor="human:staff",
            payload={"parties": len(store_case.parties), "origin": "staff-ui"},
        ))

    logger.info("staff case linked to core: yew=%s core=%s number=%s",
                store_case.id, case.id, case_number)
    return case.id
