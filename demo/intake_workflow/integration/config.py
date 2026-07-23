"""Integration configuration + shared-DB connection + aux-table management.

The integration is NATIVE in the monorepo: there is exactly one database, the
one ``core`` owns. ``shared_conn()`` opens ``core.config.get_db_path()`` with the
same pragmas /core uses. ``ensure_tables()`` creates the two integration-owned
aux tables — they are NOT /core contract tables; they are namespaced ``iw_*``
and map the intake app's local case ids to our shared case ids plus a poll
high-water mark.

Legacy note: the opt-in ``YUNAKI_SHARED_DB`` env var is GONE. ``enabled()`` now
returns True unconditionally so every existing wire-up call site stays unchanged
while the integration is always on.
"""
from __future__ import annotations

import os
import sqlite3

ENV_PORTAL_BASE = "YUNAKI_PORTAL_BASE"
DEFAULT_PORTAL_BASE = "http://localhost:8801"


def enabled() -> bool:
    """Always True: the integration is native in the monorepo.

    The function survives (rather than being deleted) purely so wire-up call
    sites that guarded on ``config.enabled()`` keep working unchanged.
    """
    return True


def portal_base() -> str:
    """Base URL for client portal deep links written back into our intake rows."""
    return os.environ.get(ENV_PORTAL_BASE, "").strip() or DEFAULT_PORTAL_BASE


def shared_conn() -> sqlite3.Connection:
    """Open a connection to the shared DB with /core-compatible pragmas.

    Connects to ``core.config.get_db_path()`` — the single monorepo database.
    row_factory=Row, foreign_keys ON, WAL journal, 5s busy timeout. The caller
    owns the connection and must close it (or use it as a context manager).

    ``core`` is imported lazily here to keep this module import-cheap and free of
    any import-ordering coupling to the /core package.
    """
    from core.config import get_db_path

    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    ensure_tables(conn)
    return conn


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the integration-owned aux tables in the shared DB. Idempotent.

    Also ensures the /core contract schema itself (event, case, draft, ...):
    on a fresh DB the intake app may be the FIRST process to touch the file,
    and the integration layer reads/writes /core tables — without this, a
    standalone `make intake` on a new DB would poll a nonexistent `event`
    table forever.

    - ``iw_case_map``   maps the intake app's local case id <-> our /core case id (1:1).
    - ``iw_bridge_state`` holds small integration cursors (the event-poll high-water).
    """
    from core.db import init_schema

    init_schema(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS iw_case_map (
            yew_case_id  TEXT PRIMARY KEY,
            core_case_id TEXT NOT NULL UNIQUE,
            created_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS iw_bridge_state (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    conn.commit()


def core_case_for(conn: sqlite3.Connection, yew_case_id: str) -> str | None:
    """Our /core case id for one of the intake app's local case ids, or None."""
    row = conn.execute(
        "SELECT core_case_id FROM iw_case_map WHERE yew_case_id = ?",
        (yew_case_id,),
    ).fetchone()
    return row["core_case_id"] if row is not None else None


def yew_case_for(conn: sqlite3.Connection, core_case_id: str) -> str | None:
    """The intake app's local case id for one of our /core case ids, or None."""
    row = conn.execute(
        "SELECT yew_case_id FROM iw_case_map WHERE core_case_id = ?",
        (core_case_id,),
    ).fetchone()
    return row["yew_case_id"] if row is not None else None


def map_case(conn: sqlite3.Connection, yew_case_id: str, core_case_id: str) -> None:
    """Record the 1:1 mapping between a local case and a /core case."""
    from datetime import datetime, timezone

    conn.execute(
        "INSERT OR IGNORE INTO iw_case_map (yew_case_id, core_case_id, created_at) "
        "VALUES (?, ?, ?)",
        (yew_case_id, core_case_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
