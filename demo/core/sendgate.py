"""The LIVE_MODE gate — CLAUDE_WORKPLAN.md §4.1.

EVERY outbound adapter in the entire system (Slack post, email send, WhatsApp)
MUST route through `execute_draft`. This is the single execution layer that
decides whether a message is really sent or merely rendered to the outbox. No
adapter may call a sender_callable, write to an inbox/API, or otherwise emit a
real message except through this function — that is what makes "agent messages a
real client" (our worst defect class) a one-line, auditable gate.

LIVE_MODE default False (see config.is_live_mode):
  - False → write the render to `outbox`, mark the draft sent (mocked), emit
    `message.sent {mocked: true}`. The sender_callable is NEVER called.
  - True  → log a LOUD warning FIRST, then call sender_callable, record the
    render, mark sent (real), emit `message.sent {mocked: false}`.

Note on the "loud warning event": the workplan event enum (§1.1) is frozen and
has no warning type — adding one would be a contract change. So the loud warning
is a CRITICAL log record (stderr banner), not an event-bus Event. The
audit-trail Event that IS emitted is the enum-legal `message.sent`, carrying
`live_mode: true` so the live send is still visible in the log.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from .config import is_live_mode
from .drafts import get_draft, mark_sent
from .events import emit
from .models import Event

logger = logging.getLogger("yunaki.sendgate")

# A draft-shaped callable that performs the real-world side effect.
SenderCallable = Callable[..., Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_outbox(
    conn: sqlite3.Connection, draft_id: str, channel: str, live: bool
) -> None:
    conn.execute(
        "INSERT INTO outbox (id, draft_id, channel, rendered_at, live_mode_at_render) "
        "VALUES (?, ?, ?, ?, ?)",
        (f"outbox_{uuid4().hex}", draft_id, channel, _now_iso(), 1 if live else 0),
    )
    conn.commit()


def execute_draft(
    conn: sqlite3.Connection,
    draft_id: str,
    sender_callable: SenderCallable,
    *,
    actor: str = "agent:slack",
) -> dict[str, Any]:
    """Execute an approved draft through the single LIVE_MODE gate.

    Returns a small result dict describing what happened. Raises if the draft is
    missing or not approved — a send is impossible without prior approval.
    """
    draft = get_draft(conn, draft_id)
    if draft is None:
        raise LookupError(f"draft {draft_id!r} does not exist")
    if draft.state != "approved":
        raise ValueError(
            f"execute_draft requires an approved draft; {draft_id!r} is "
            f"{draft.state!r} (guardrail §4.2)"
        )

    live = is_live_mode()

    if not live:
        _write_outbox(conn, draft_id, draft.kind, live=False)
        mark_sent(conn, draft_id, mocked=True, channel=draft.kind)
        emit(
            conn,
            Event(
                type="message.sent",
                case_id=draft.case_id,
                actor=actor,
                payload={"mocked": True, "draft_id": draft_id, "channel": draft.kind},
            ),
        )
        return {"mocked": True, "draft_id": draft_id, "channel": draft.kind}

    # LIVE_MODE=true — loud warning FIRST, then the real side effect.
    logger.critical(
        "LIVE_MODE ACTIVE — sending a REAL %s to %s <%s> for draft %s. "
        "This is a real outbound message.",
        draft.kind,
        draft.to.name,
        draft.to.channel_address,
        draft_id,
    )
    sender_callable(draft)
    _write_outbox(conn, draft_id, draft.kind, live=True)
    mark_sent(conn, draft_id, mocked=False, channel=draft.kind)
    emit(
        conn,
        Event(
            type="message.sent",
            case_id=draft.case_id,
            actor=actor,
            payload={
                "mocked": False,
                "live_mode": True,
                "draft_id": draft_id,
                "channel": draft.kind,
            },
        ),
    )
    return {"mocked": False, "live_mode": True, "draft_id": draft_id, "channel": draft.kind}
