"""Gmail-agent-PRIVATE persistence — mirrors slack_agent/threads.py.

These aux tables live on the SHARED core DB but are owned exclusively by
gmail_agent. Creating them from here (CREATE TABLE IF NOT EXISTS) is NOT a /core
edit — /core owns the contract tables (event, draft, case, ...); these two are
namespaced `gmail_*` and no other workstream reads or writes them:

  gmail_state         key/value scratch: the history high-water mark (the cursor
                      users.history.list resumes from) and the watch expiration
                      (so the runner can re-register within 24h of expiry).
  gmail_seen_message  the dedup ledger, keyed by Gmail message id. A message id
                      recorded here has been fully handled (processed, or a
                      deterministic skip: own-address / no-body), so overlapping
                      history windows and Pub/Sub redeliveries can never produce
                      a second email.received or draft.created for it.

HIGH-WATER + DEDUP INTERACTION (why both exist):
  - The high-water mark is the COARSE cursor: history.list(startHistoryId=hw)
    bounds how much history we re-scan. It advances only AFTER a notification's
    whole batch processes successfully, so a crash mid-batch re-scans from the
    old mark rather than skipping messages.
  - The dedup ledger is the FINE idempotency guarantee: it is written per
    message only after that message is fully handled. So re-scanning an
    overlapping window (or a nacked+redelivered notification) reprocesses only
    the messages that had NOT completed; anything already done is skipped. A
    message that errored is left unrecorded on purpose — it is retried, loudly.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

_HIGH_WATER_KEY = "history_high_water"
_WATCH_EXPIRATION_KEY = "watch_expiration_ms"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the gmail_agent-private aux tables. Idempotent."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS gmail_state (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gmail_seen_message (
            message_id TEXT PRIMARY KEY,
            seen_at    TEXT NOT NULL
        );
        """
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Dedup ledger
# --------------------------------------------------------------------------- #

def is_seen(conn: sqlite3.Connection, message_id: str) -> bool:
    """True if this Gmail message id has already been fully handled."""
    row = conn.execute(
        "SELECT 1 FROM gmail_seen_message WHERE message_id = ?", (message_id,)
    ).fetchone()
    return row is not None


def mark_seen(conn: sqlite3.Connection, message_id: str) -> bool:
    """Record a message id as fully handled. INSERT OR IGNORE.

    Returns True if this call inserted the row (first time), False if it was
    already present. Callers invoke this only AFTER a message is processed or
    deterministically skipped — never before, so an errored message stays
    unrecorded and is retried.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO gmail_seen_message (message_id, seen_at) VALUES (?, ?)",
        (message_id, _now_iso()),
    )
    conn.commit()
    return cur.rowcount == 1


# --------------------------------------------------------------------------- #
# Key/value state: history high-water mark + watch expiration
# --------------------------------------------------------------------------- #

def _get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM gmail_state WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else None


def _set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO gmail_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def get_high_water(conn: sqlite3.Connection) -> int | None:
    """The stored history high-water mark (a Gmail historyId), or None if the
    baseline has never been set (watch not yet registered)."""
    raw = _get(conn, _HIGH_WATER_KEY)
    return int(raw) if raw is not None else None


def set_high_water(conn: sqlite3.Connection, history_id: int) -> None:
    """Advance (or set) the high-water mark. Never moves backwards."""
    current = get_high_water(conn)
    if current is None or history_id > current:
        _set(conn, _HIGH_WATER_KEY, str(history_id))


def get_watch_expiration(conn: sqlite3.Connection) -> int | None:
    """Stored watch expiration in epoch milliseconds, or None if unset."""
    raw = _get(conn, _WATCH_EXPIRATION_KEY)
    return int(raw) if raw is not None else None


def set_watch_expiration(conn: sqlite3.Connection, expiration_ms: int) -> None:
    _set(conn, _WATCH_EXPIRATION_KEY, str(expiration_ms))
