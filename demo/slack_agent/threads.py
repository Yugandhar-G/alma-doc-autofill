"""Workstream-A-PRIVATE persistence — CLAUDE_WORKPLAN.md §2.6.

These aux tables live on the SHARED core DB but are owned exclusively by
slack_agent. Creating them from here (CREATE TABLE IF NOT EXISTS) is NOT a /core
edit — /core owns the contract tables (event, draft, case, ...); these three are
namespaced `slack_*` and no other workstream reads or writes them:

  slack_thread        case_id ↔ (channel, thread_ts) mapping so drafts/escalations
                      land back in the originating handoff thread.
  slack_agent_state   key/value scratch: the poller high-water mark and the
                      per-case "chasing paused" flags.
  slack_seen_event    the dedup ledger — an event id claimed here has been (or is
                      being) handled, so the in-process pubsub and the cross-process
                      poller can never post the same draft/escalation twice.

All access is on the single asyncio-loop thread (one sqlite connection), so no
locking beyond SQLite's own is needed.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

_HIGH_WATER_KEY = "poll_high_water"
_PAUSE_PREFIX = "pause:"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the slack_agent-private aux tables. Idempotent."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS slack_thread (
            case_id    TEXT PRIMARY KEY,
            channel    TEXT NOT NULL,
            thread_ts  TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS slack_agent_state (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS slack_seen_event (
            event_id TEXT PRIMARY KEY,
            seen_at  TEXT NOT NULL
        );
        """
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Thread mapping
# --------------------------------------------------------------------------- #

def map_thread(
    conn: sqlite3.Connection, case_id: str, channel: str, thread_ts: str
) -> None:
    """Record where a case's conversation lives. Last write wins."""
    conn.execute(
        "INSERT INTO slack_thread (case_id, channel, thread_ts, created_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(case_id) DO UPDATE SET channel=excluded.channel, "
        "thread_ts=excluded.thread_ts",
        (case_id, channel, thread_ts, _now_iso()),
    )
    conn.commit()


def get_thread(conn: sqlite3.Connection, case_id: str) -> dict[str, str] | None:
    """Return {'channel', 'thread_ts'} for a case, or None if unmapped."""
    row = conn.execute(
        "SELECT channel, thread_ts FROM slack_thread WHERE case_id = ?", (case_id,)
    ).fetchone()
    if row is None:
        return None
    return {"channel": row["channel"], "thread_ts": row["thread_ts"]}


def get_case_by_thread(
    conn: sqlite3.Connection, channel: str, thread_ts: str
) -> str | None:
    """Reverse lookup: which case does this Slack thread belong to?

    Used by the mention agent so "@yunaki ..." inside a handoff thread is
    automatically scoped to that thread's case without the human naming it.
    """
    row = conn.execute(
        "SELECT case_id FROM slack_thread WHERE channel = ? AND thread_ts = ?",
        (channel, thread_ts),
    ).fetchone()
    return row["case_id"] if row else None


# --------------------------------------------------------------------------- #
# Dedup ledger — the seam between the in-process pubsub and the poller
# --------------------------------------------------------------------------- #

def claim_event(conn: sqlite3.Connection, event_id: str) -> bool:
    """Atomically claim an event id for handling.

    Returns True exactly once per event id (the caller should then handle it),
    False on every subsequent attempt. INSERT OR IGNORE + rowcount is the atomic
    test-and-set that makes the dual consumption paths idempotent.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO slack_seen_event (event_id, seen_at) VALUES (?, ?)",
        (event_id, _now_iso()),
    )
    conn.commit()
    return cur.rowcount == 1


# --------------------------------------------------------------------------- #
# Key/value state: poller high-water mark + pause flags
# --------------------------------------------------------------------------- #

def _get_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM slack_agent_state WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else None


def _set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO slack_agent_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def get_high_water(conn: sqlite3.Connection) -> int:
    """Highest event rowid the poller has already scanned (0 if never)."""
    raw = _get_state(conn, _HIGH_WATER_KEY)
    return int(raw) if raw is not None else 0


def set_high_water(conn: sqlite3.Connection, rowid: int) -> None:
    _set_state(conn, _HIGH_WATER_KEY, str(rowid))


def set_pause(conn: sqlite3.Connection, case_id: str, paused: bool) -> None:
    """Record/clear the 'chasing paused' flag for a case."""
    _set_state(conn, _PAUSE_PREFIX + case_id, "1" if paused else "0")


def is_paused(conn: sqlite3.Connection, case_id: str) -> bool:
    return _get_state(conn, _PAUSE_PREFIX + case_id) == "1"
