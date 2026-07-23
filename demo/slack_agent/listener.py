"""Case-handoff listener — CLAUDE_WORKPLAN.md §2 item 2 (amended Jul 22).

Watches top-level messages in SLACK_CHANNEL_CASES (not thread replies, not bot
messages) and hands each one to the kernel deep-agent loop
(`handoff_agent.run_handoff`). The agent parses, checks for existing clients,
creates the case (or asks in-thread), emits `case.handoff_received`, replies in
the message's own thread, and persists its transcript — this module only owns
the Bolt event filter (`should_handle`) and the thin delegation.

*(Amended Jul 22: the single structured-output parse was replaced by a real
agent loop — the filter is unchanged; the parsing/creation body moved into
handoff_agent.)*
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from slack_agent import handoff_agent

logger = logging.getLogger("slack_agent.listener")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_HANDOFF_KEYWORDS = (
    "new case",
    "open a case",
    "new client",
    "new matter",
    "handoff",
    "hand off",
    "petitioner",
    "beneficiary",
)


def looks_like_handoff(text: str) -> bool:
    """Heuristic gate: does a tagged ask look like a case handoff (create) vs a
    question (answer)? A client email address is the strongest signal; explicit
    handoff language is the fallback. The handoff agent still applies null-over-
    guess after this, so a false positive just means it asks for the fields."""
    if _EMAIL_RE.search(text or ""):
        return True
    lowered = (text or "").lower()
    return any(k in lowered for k in _HANDOFF_KEYWORDS)


def should_handle(
    event: dict[str, Any], channel_cases: str, bot_user_id: str | None = None
) -> bool:
    """True only for a human top-level post in the cases channel."""
    if event.get("channel") != channel_cases:
        return False
    if event.get("bot_id") or event.get("subtype"):
        return False  # bot messages / edits / joins etc.
    thread_ts = event.get("thread_ts")
    ts = event.get("ts")
    if thread_ts and thread_ts != ts:
        return False  # a reply inside a thread, not a new handoff
    text = event.get("text") or ""
    if not text.strip():
        return False
    if bot_user_id and f"<@{bot_user_id}>" in text:
        return False  # "@yunaki ..." is a mention-agent ask, not a case handoff
    return True


async def handle_handoff_message(
    *,
    conn: sqlite3.Connection,
    client: Any,
    channel: str,
    message_ts: str,
    text: str,
) -> str | None:
    """Delegate one handoff message to the kernel agent. Returns case_id or None.

    All parsing, existing-client lookup, case creation (null over guess), event
    emission, thread mapping, and the in-thread reply live in
    handoff_agent.run_handoff — the agent never guesses a case, and asks
    in-thread when nothing is parseable.
    """
    return await handoff_agent.run_handoff(
        conn=conn,
        client=client,
        channel=channel,
        message_ts=message_ts,
        text=text,
    )
