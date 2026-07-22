"""Connection factory + idempotent schema — CLAUDE_WORKPLAN.md §1 + §4.

Guardrails are enforced in the DDL itself, not by convention:
  - event.type CHECK against the closed enum (§1.1)
  - draft.state CHECK on (pending|approved|rejected|sent) (§1.2)
  - a `message_sent` ledger whose insert is blocked by a trigger unless the
    referenced draft has reached approved/sent (§4.2 — the DB half of "no send
    without approval"; the code half lives in drafts.mark_sent)
  - an `outbox` table (§4.1) recording every rendered-but-not-live message.

All enum value sets are imported from models.py so the schema can never drift
from the pydantic contracts.
"""

from __future__ import annotations

import sqlite3

from .config import get_db_path
from .models import (
    CHECKLIST_STATES,
    DRAFT_KINDS,
    DRAFT_STATES,
    DRAFT_TRIGGERS,
    EVENT_TYPES,
    INTAKE_STATES,
    PARTY_ROLES,
)


def _sql_enum(values: tuple[str, ...]) -> str:
    """Render a tuple of enum values as a SQL IN-list, e.g. "'a', 'b'"."""
    return ", ".join(f"'{v}'" for v in values)


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with FK enforcement and Row access.

    Reads DB_PATH from env (default ./yunaki.db) when no path is given.
    """
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ddl() -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS "case" (
        id           TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        process_type TEXT NOT NULL,
        stage        TEXT NOT NULL,
        created_at   TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS client (
        id         TEXT PRIMARY KEY,
        first_name TEXT NOT NULL,
        last_name  TEXT NOT NULL,
        email      TEXT,
        phone      TEXT,
        whatsapp   TEXT
    );

    CREATE TABLE IF NOT EXISTS party (
        case_id   TEXT NOT NULL REFERENCES "case"(id),
        client_id TEXT NOT NULL REFERENCES client(id),
        role      TEXT NOT NULL CHECK (role IN ({_sql_enum(PARTY_ROLES)})),
        PRIMARY KEY (case_id, client_id)
    );

    CREATE TABLE IF NOT EXISTS intake (
        id                      TEXT PRIMARY KEY,
        case_id                 TEXT NOT NULL REFERENCES "case"(id),
        client_id               TEXT NOT NULL REFERENCES client(id),
        url                     TEXT NOT NULL,
        state                   TEXT NOT NULL CHECK (state IN ({_sql_enum(INTAKE_STATES)})),
        sent_at                 TEXT,
        last_client_activity_at TEXT
    );

    CREATE TABLE IF NOT EXISTS checklist_item (
        id                TEXT PRIMARY KEY,
        intake_id         TEXT NOT NULL REFERENCES intake(id),
        seq               INTEGER NOT NULL,
        label             TEXT NOT NULL,
        mandatory_to_file INTEGER NOT NULL DEFAULT 1,
        state             TEXT NOT NULL CHECK (state IN ({_sql_enum(CHECKLIST_STATES)}))
    );

    -- §1.1 event bus. type CHECK is the schema-enforced closed enum.
    CREATE TABLE IF NOT EXISTS event (
        id      TEXT PRIMARY KEY,
        ts      TEXT NOT NULL,
        type    TEXT NOT NULL CHECK (type IN ({_sql_enum(EVENT_TYPES)})),
        case_id TEXT,
        actor   TEXT NOT NULL,
        payload TEXT NOT NULL DEFAULT '{{}}'
    );
    CREATE INDEX IF NOT EXISTS idx_event_case ON event(case_id);
    CREATE INDEX IF NOT EXISTS idx_event_type ON event(type);

    -- §1.2 DraftAction. state CHECK is schema-enforced.
    CREATE TABLE IF NOT EXISTS draft (
        id                 TEXT PRIMARY KEY,
        case_id            TEXT NOT NULL,
        kind               TEXT NOT NULL CHECK (kind IN ({_sql_enum(DRAFT_KINDS)})),
        trigger            TEXT NOT NULL CHECK (trigger IN ({_sql_enum(DRAFT_TRIGGERS)})),
        to_name            TEXT NOT NULL,
        to_channel_address TEXT NOT NULL,
        subject            TEXT,
        body               TEXT NOT NULL,
        grounding          TEXT NOT NULL DEFAULT '{{}}',
        state              TEXT NOT NULL DEFAULT 'pending'
                           CHECK (state IN ({_sql_enum(DRAFT_STATES)}))
    );

    -- §4.1 outbox: every rendered-but-not-sent message lands here in mock mode.
    CREATE TABLE IF NOT EXISTS outbox (
        id                 TEXT PRIMARY KEY,
        draft_id           TEXT NOT NULL REFERENCES draft(id),
        channel            TEXT NOT NULL,
        rendered_at        TEXT NOT NULL,
        live_mode_at_render INTEGER NOT NULL
    );

    -- §4.2 message_sent ledger. Insert is GUARDED by the trigger below: a row
    -- cannot exist unless its draft reached approved/sent. This is the DB half
    -- of "no send without approval"; drafts.mark_sent is the code half.
    CREATE TABLE IF NOT EXISTS message_sent (
        id       TEXT PRIMARY KEY,
        draft_id TEXT NOT NULL REFERENCES draft(id),
        channel  TEXT NOT NULL,
        sent_at  TEXT NOT NULL,
        mocked   INTEGER NOT NULL
    );

    CREATE TRIGGER IF NOT EXISTS trg_message_sent_requires_approval
    BEFORE INSERT ON message_sent
    FOR EACH ROW
    WHEN (SELECT state FROM draft WHERE id = NEW.draft_id) NOT IN ('approved', 'sent')
    BEGIN
        SELECT RAISE(ABORT, 'message_sent blocked: draft not approved (guardrail §4.2)');
    END;
    """


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables, indexes, and triggers. Idempotent."""
    conn.executescript(_ddl())
    conn.commit()


def connect_and_init(db_path: str | None = None) -> sqlite3.Connection:
    """Convenience: open a connection and ensure the schema exists."""
    conn = get_connection(db_path)
    init_schema(conn)
    return conn
