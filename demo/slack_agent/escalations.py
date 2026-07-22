"""Escalation surfacing — CLAUDE_WORKPLAN.md §2 item 4.

Consumes escalation.raised (from Workstream B) and posts it into the case thread
with demo-grade quick actions. "Send again" creates a NEW pending DraftAction
(trigger=manual) that flows through the normal approval path; "Call client" and
"Pause chasing" are recorded/acknowledged with no client-bound side effect.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from core import drafts
from core.events import emit
from core.models import DraftAction, DraftGrounding, DraftTo, Event
from slack_agent import blocks, threads

logger = logging.getLogger("slack_agent.escalations")


def _case_name(conn: sqlite3.Connection, case_id: str) -> str:
    row = conn.execute('SELECT name FROM "case" WHERE id = ?', (case_id,)).fetchone()
    return row["name"] if row else case_id


async def post_escalation(
    conn: sqlite3.Connection, client: Any, event: Event, *, fallback_channel: str
) -> None:
    case_id = event.case_id or ""
    mapping = threads.get_thread(conn, case_id)
    if mapping:
        channel, thread_ts = mapping["channel"], mapping["thread_ts"]
    else:
        channel, thread_ts = fallback_channel, None
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        blocks=blocks.escalation_blocks(case_id, _case_name(conn, case_id)),
        text="Escalation — client not responding",
    )
    logger.info("posted escalation for case=%s", case_id)


def _last_nudge_draft(conn: sqlite3.Connection, case_id: str) -> DraftAction | None:
    row = conn.execute(
        "SELECT id FROM draft WHERE case_id = ? AND kind IN "
        "('client_email', 'client_whatsapp') ORDER BY rowid DESC LIMIT 1",
        (case_id,),
    ).fetchone()
    return drafts.get_draft(conn, row["id"]) if row else None


def _petitioner_contact(conn: sqlite3.Connection, case_id: str) -> DraftTo:
    row = conn.execute(
        'SELECT c.first_name, c.last_name, c.email FROM party p '
        "JOIN client c ON c.id = p.client_id "
        "WHERE p.case_id = ? ORDER BY (p.role = 'petitioner') DESC LIMIT 1",
        (case_id,),
    ).fetchone()
    if row is None:
        return DraftTo(name="client", channel_address="unknown@example.com")
    name = " ".join(x for x in (row["first_name"], row["last_name"]) if x) or "client"
    return DraftTo(name=name, channel_address=row["email"] or "unknown@example.com")


async def send_again(
    conn: sqlite3.Connection, client: Any, case_id: str, *, channel: str, message_ts: str
) -> str:
    """Create a fresh manual nudge draft; it flows through the approval path."""
    threads.set_pause(conn, case_id, False)  # sending again un-pauses chasing
    prior = _last_nudge_draft(conn, case_id)
    if prior is not None:
        draft = DraftAction(
            case_id=case_id,
            kind=prior.kind,
            trigger="manual",
            to=prior.to,
            subject=prior.subject,
            body=prior.body,
            grounding=prior.grounding,
        )
    else:
        draft = DraftAction(
            case_id=case_id,
            kind="client_email",
            trigger="manual",
            to=_petitioner_contact(conn, case_id),
            subject="Following up on your intake",
            body="Hi — just following up on the documents we still need from you.",
            grounding=DraftGrounding(),
        )
    created = drafts.create_draft(conn, draft)
    emit(
        conn,
        Event(
            type="draft.created",
            case_id=case_id,
            actor="agent:slack",
            payload={"draft_id": created.id, "kind": created.kind, "channel": created.kind},
        ),
    )
    await client.chat_update(
        channel=channel,
        ts=message_ts,
        blocks=blocks.escalation_resolved_blocks(
            _case_name(conn, case_id), "🔁 New reminder drafted — awaiting approval"
        ),
        text="Escalation — reminder drafted",
    )
    logger.info("escalation send_again created draft=%s case=%s", created.id, case_id)
    return created.id


async def call_client(
    conn: sqlite3.Connection, client: Any, case_id: str, *, channel: str, message_ts: str
) -> None:
    await client.chat_update(
        channel=channel,
        ts=message_ts,
        blocks=blocks.escalation_resolved_blocks(
            _case_name(conn, case_id), "📞 Task assigned: call the client"
        ),
        text="Escalation — task assigned",
    )
    logger.info("escalation call_client case=%s", case_id)


async def pause_chasing(
    conn: sqlite3.Connection, client: Any, case_id: str, *, channel: str, message_ts: str
) -> None:
    threads.set_pause(conn, case_id, True)
    await client.chat_update(
        channel=channel,
        ts=message_ts,
        blocks=blocks.escalation_resolved_blocks(
            _case_name(conn, case_id), "⏸️ Chasing paused"
        ),
        text="Escalation — chasing paused",
    )
    logger.info("escalation pause_chasing case=%s", case_id)
