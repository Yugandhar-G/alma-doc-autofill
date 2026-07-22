"""dev_stub — the fake Workstream B — CLAUDE_WORKPLAN.md §2 DoD.

Until Workstream B lands, this is how the DoD chain gets demoed and tested. It
seeds the DB (reusing the real seed script), then emits either a realistic nudge
`draft.created` or an `escalation.raised` for the seeded case — as a SEPARATE
process from the running slack_agent, so it exercises the cross-process poller
seam (the in-process pubsub can't reach across processes).

  python -m slack_agent.dev_stub            # emit a nudge draft.created
  python -m slack_agent.dev_stub nudge
  python -m slack_agent.dev_stub escalation # emit escalation.raised
"""

from __future__ import annotations

import sqlite3
import sys

from core import drafts
from core.db import connect_and_init
from core.events import emit
from core.models import DraftAction, DraftGrounding, DraftTo, Event
from seed import seed_case

# 3 checklist labels copied VERBATIM from the seeded petitioner questionnaire.
_MISSING_ITEMS = [seed_case.PETITIONER_CHECKLIST[i][1] for i in (5, 6, 8)]


def _petitioner_to(conn: sqlite3.Connection) -> DraftTo:
    row = conn.execute(
        "SELECT first_name, last_name, email FROM client WHERE id = ?",
        (seed_case.PETITIONER_ID,),
    ).fetchone()
    name = " ".join(x for x in (row["first_name"], row["last_name"]) if x)
    return DraftTo(name=name, channel_address=row["email"])


def emit_nudge(conn: sqlite3.Connection, case_id: str = seed_case.CASE_ID) -> str:
    """Create a realistic nudge draft (days_since_activity=4) + emit draft.created."""
    body = (
        "Hi Ravi, we're still missing a few documents to move your case forward:\n"
        + "\n".join(f"• {item}" for item in _MISSING_ITEMS)
        + "\n\nCould you upload these when you get a chance? Thank you."
    )
    draft = DraftAction(
        case_id=case_id,
        kind="client_email",
        trigger="followup_timer",
        to=_petitioner_to(conn),
        subject="A few documents still needed",
        body=body,
        grounding=DraftGrounding(missing_items=list(_MISSING_ITEMS), days_since_activity=4),
    )
    created = drafts.create_draft(conn, draft)
    emit(
        conn,
        Event(
            type="draft.created",
            case_id=case_id,
            actor="agent:validation",  # pretend to be Workstream B
            payload={"draft_id": created.id, "kind": created.kind, "channel": created.kind},
        ),
    )
    print(f"emitted draft.created draft_id={created.id} case={case_id}")
    return created.id


def emit_escalation(conn: sqlite3.Connection, case_id: str = seed_case.CASE_ID) -> None:
    """Emit escalation.raised as Workstream B would after 2 unanswered nudges."""
    emit(
        conn,
        Event(
            type="escalation.raised",
            case_id=case_id,
            actor="agent:followup",
            payload={"reason": "two_unanswered_nudges", "nudges": 2},
        ),
    )
    print(f"emitted escalation.raised case={case_id}")


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "nudge"
    conn = connect_and_init()
    try:
        case_id = seed_case.seed(conn)
        if mode == "escalation":
            emit_escalation(conn, case_id)
        elif mode == "nudge":
            emit_nudge(conn, case_id)
        else:
            print(f"unknown mode {mode!r} (use 'nudge' or 'escalation')", file=sys.stderr)
            return 2
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
