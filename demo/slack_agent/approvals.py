"""Approval flow — CLAUDE_WORKPLAN.md §2 item 3 + §4.1/§4.2.

Posts each draft.created into the case's Slack thread (falling back to the cases
channel when unmapped) and handles the [Approve] [Edit] [Reject] buttons/modals.

Every outbound *client-bound* send goes through core.sendgate.execute_draft — the
ONLY execution layer (§4.1). With LIVE_MODE=false it renders to the outbox and
emits message.sent {mocked:true}; the sender callable is never invoked. Slack
posts (the control surface) are made directly and are allowed (§4).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Any, Awaitable, Callable

from core import drafts, sendgate
from core.events import emit
from core.models import Event
from slack_agent import blocks, senders, threads

logger = logging.getLogger("slack_agent.approvals")

AckFn = Callable[[], Awaitable[None]]


async def post_approval(
    conn: sqlite3.Connection, client: Any, draft: DraftAction, *, fallback_channel: str
) -> dict[str, str]:
    """Post the approval block into the case thread (or the cases channel)."""
    mapping = threads.get_thread(conn, draft.case_id)
    if mapping:
        channel, thread_ts = mapping["channel"], mapping["thread_ts"]
    else:
        channel, thread_ts = fallback_channel, None
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        # Approval cards live in the case thread for context, but must never
        # hide there: reply_broadcast surfaces them in the channel too —
        # an unseen approval card is an unanswered client.
        reply_broadcast=True if thread_ts else None,
        blocks=blocks.approval_blocks(draft),
        text="Draft ready for review",
    )
    logger.info("posted approval for draft=%s case=%s", draft.id, draft.case_id)
    return {"channel": channel}


async def approve(
    conn: sqlite3.Connection,
    client: Any,
    draft_id: str,
    *,
    channel: str,
    message_ts: str,
    ack: AckFn | None = None,
) -> "asyncio.Task[dict[str, Any]]":
    """Ack Slack immediately (<3s, always), then run the send OFF the ack path.

    Latency contract §2.8: the acknowledgement must return within 3s regardless
    of how slow the send is, so the actual work (draft state change → sendgate
    execute → event → Slack message update) runs in a background asyncio task.

    In production main.py already awaits ack() before calling us and ignores the
    returned task — the work continues on the Bolt loop. When an `ack` callable
    is passed (tests, or a future direct-handler wiring) we ack here first. The
    returned Task lets a caller await completion; awaiting is never required.
    """
    if ack is not None:
        await ack()
    return asyncio.create_task(
        _run_approval_work(
            conn, client, draft_id, channel=channel, message_ts=message_ts
        )
    )


async def _run_approval_work(
    conn: sqlite3.Connection,
    client: Any,
    draft_id: str,
    *,
    channel: str,
    message_ts: str,
) -> dict[str, Any]:
    """The real approval work, run in the background task. Failures NEVER go
    silent (§2.8): they log loudly AND surface a visible error line in Slack."""
    try:
        # §4.2 ordering: the approve state change commits BEFORE execute_draft
        # (execute_draft itself refuses any draft not in state 'approved').
        drafts.approve_draft(conn, draft_id)
        emit(
            conn,
            Event(
                type="draft.approved",
                case_id=_case_id(conn, draft_id),
                actor="human:paralegal",
                payload={"draft_id": draft_id},
            ),
        )
        draft = drafts.get_draft(conn, draft_id)
        # Resolve the real-world send for this kind; fall back to the no-op
        # placeholder (never invoked under LIVE_MODE=false). §4.1: execute_draft
        # is still the single gate — the registry only decides WHICH callable.
        sender = senders.get_sender(draft.kind) or senders.noop_sender
        result = sendgate.execute_draft(conn, draft_id, sender, actor="agent:slack")
        draft = drafts.get_draft(conn, draft_id)
        await client.chat_update(
            channel=channel,
            ts=message_ts,
            blocks=blocks.approved_blocks(draft),
            text="Draft approved",
        )
        logger.info("approved draft=%s mocked=%s", draft_id, result.get("mocked"))
        return result
    except Exception as exc:  # noqa: BLE001 - fail loud + visible, never silent (§2.8)
        logger.exception("approval work FAILED for draft=%s", draft_id)
        status = (
            f"Could not complete the send: {type(exc).__name__}. See agent logs."
        )
        try:
            await client.chat_update(
                channel=channel,
                ts=message_ts,
                blocks=blocks.approval_error_blocks(status),
                text="Approval failed",
            )
        except Exception:  # noqa: BLE001 - the loud log above is the last resort
            logger.exception(
                "also failed to surface approval error to Slack for draft=%s",
                draft_id,
            )
        return {"error": type(exc).__name__, "draft_id": draft_id}


async def open_reject_modal(
    client: Any, *, trigger_id: str, draft_id: str, channel: str, message_ts: str
) -> None:
    await client.views_open(
        trigger_id=trigger_id,
        view=blocks.reject_modal_view(
            {"draft_id": draft_id, "channel": channel, "message_ts": message_ts}
        ),
    )


async def submit_reject(
    conn: sqlite3.Connection,
    client: Any,
    draft_id: str,
    reason: str | None,
    *,
    channel: str,
    message_ts: str,
) -> None:
    drafts.reject_draft(conn, draft_id)
    emit(
        conn,
        Event(
            type="draft.rejected",
            case_id=_case_id(conn, draft_id),
            actor="human:paralegal",
            payload={"draft_id": draft_id, "reason": reason},
        ),
    )
    draft = drafts.get_draft(conn, draft_id)
    await client.chat_update(
        channel=channel,
        ts=message_ts,
        blocks=blocks.rejected_blocks(draft, reason),
        text="Draft rejected",
    )
    logger.info("rejected draft=%s", draft_id)


async def open_edit_modal(
    conn: sqlite3.Connection,
    client: Any,
    *,
    trigger_id: str,
    draft_id: str,
    channel: str,
    message_ts: str,
) -> None:
    draft = drafts.get_draft(conn, draft_id)
    if draft is None:
        return
    await client.views_open(
        trigger_id=trigger_id,
        view=blocks.edit_modal_view(
            draft, {"draft_id": draft_id, "channel": channel, "message_ts": message_ts}
        ),
    )


def _update_draft_body(conn: sqlite3.Connection, draft_id: str, body: str) -> bool:
    """Guarded body update on a still-pending draft.

    core.drafts exposes no body-mutation helper, so we UPDATE the core-owned
    draft table directly, guarded on state='pending' so an approved/sent/rejected
    draft can never be silently edited. Flagged as contract friction — a
    core.drafts.update_body would be the clean home for this.
    """
    cur = conn.execute(
        "UPDATE draft SET body = ? WHERE id = ? AND state = 'pending'",
        (body, draft_id),
    )
    conn.commit()
    return cur.rowcount == 1


async def submit_edit(
    conn: sqlite3.Connection,
    client: Any,
    draft_id: str,
    new_body: str,
    *,
    channel: str,
    message_ts: str,
) -> None:
    if not _update_draft_body(conn, draft_id, new_body):
        logger.warning("edit ignored — draft=%s not pending", draft_id)
        return
    draft = drafts.get_draft(conn, draft_id)
    await client.chat_update(
        channel=channel,
        ts=message_ts,
        blocks=blocks.approval_blocks(draft),  # still pending, re-rendered
        text="Draft updated",
    )
    logger.info("edited draft=%s (still pending)", draft_id)


def _case_id(conn: sqlite3.Connection, draft_id: str) -> str:
    draft = drafts.get_draft(conn, draft_id)
    return draft.case_id if draft else ""
