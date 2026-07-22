"""Case-handoff listener — CLAUDE_WORKPLAN.md §2 item 2.

Watches top-level messages in SLACK_CHANNEL_CASES (not thread replies, not bot
messages), parses them via ONE structured LLM call, and on success opens the
case through /core and replies in the message's own thread with what was
captured + explicit asks for every null.

The core logic (`handle_handoff_message`) takes an injected `parse` callable and
an explicit Slack client so it is testable without Bolt or the network. The Bolt
event filter lives in `should_handle`.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Awaitable, Callable

from core.events import emit
from core.models import Event
from slack_agent import blocks, casewrite, threads
from slack_agent.handoff_parser import HandoffParse, parse_handoff

logger = logging.getLogger("slack_agent.listener")

ParseFn = Callable[[str], Awaitable[HandoffParse]]


def should_handle(event: dict[str, Any], channel_cases: str) -> bool:
    """True only for a human top-level post in the cases channel."""
    if event.get("channel") != channel_cases:
        return False
    if event.get("bot_id") or event.get("subtype"):
        return False  # bot messages / edits / joins etc.
    thread_ts = event.get("thread_ts")
    ts = event.get("ts")
    if thread_ts and thread_ts != ts:
        return False  # a reply inside a thread, not a new handoff
    if not (event.get("text") or "").strip():
        return False
    return True


async def handle_handoff_message(
    *,
    conn: sqlite3.Connection,
    client: Any,
    channel: str,
    message_ts: str,
    text: str,
    parse: ParseFn = parse_handoff,
) -> str | None:
    """Parse → open case → emit → map thread → reply. Returns case_id or None.

    When nothing parses (no parties), creates NOTHING and asks for the fields —
    the model's absence of output must never become invented case data (§4.3).
    """
    result = await parse(text)

    if not result.parties:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=message_ts,
            blocks=blocks.ask_for_fields_blocks(result.available),
            text="Handoff needs more detail",
        )
        return None

    handoff = casewrite.create_handoff_case(conn, result)
    case = handoff.case

    emit(
        conn,
        Event(
            type="case.handoff_received",
            case_id=case.id,
            actor="agent:slack",
            payload={
                "parties": len(handoff.parties),
                "process_type_known": bool(case.process_type),
                "missing_count": len(handoff.missing),
            },
        ),
    )

    threads.map_thread(conn, case.id, channel, message_ts)

    await client.chat_postMessage(
        channel=channel,
        thread_ts=message_ts,
        blocks=blocks.handoff_summary_blocks(
            case.name, case.process_type, handoff.captured_lines, handoff.missing
        ),
        text=f"Case handoff captured — {case.name}",
    )
    logger.info("handoff opened case=%s parties=%d", case.id, len(handoff.parties))
    return case.id
