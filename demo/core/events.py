"""Append-only event bus + in-process pubsub — CLAUDE_WORKPLAN.md §1.1.

emit() validates through the pydantic Event model (whose `type` is the closed
enum) before it ever touches SQLite, then inserts, then fires subscribers
synchronously. Both the pydantic Literal and the DB CHECK reject unknown types,
so the enum is enforced twice and lives in exactly one place (models.py).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Callable

from .models import Event

# In-process pubsub: event type -> callbacks fired synchronously after insert.
EventCallback = Callable[[Event], None]
_subscribers: dict[str, list[EventCallback]] = {}


def subscribe(event_type: str, callback: EventCallback) -> None:
    """Register a callback fired (synchronously) after an event of this type is
    successfully appended. Kept as a simple dict per the frozen contract."""
    _subscribers.setdefault(event_type, []).append(callback)


def clear_subscribers() -> None:
    """Drop all subscribers. For test isolation and clean shutdown."""
    _subscribers.clear()


def emit(conn: sqlite3.Connection, event: Event) -> Event:
    """Validate → insert → commit → fire subscribers. Fails loud on bad input.

    `event` must already be an Event instance (constructed by the caller so the
    pydantic validation happens at their boundary); we re-validate defensively.
    """
    if not isinstance(event, Event):
        raise TypeError(f"emit() requires an Event, got {type(event).__name__}")
    # Re-validate defensively: guarantees the enum/actor invariants hold even if
    # the instance was mutated after construction.
    event = Event.model_validate(event.model_dump())

    conn.execute(
        "INSERT INTO event (id, ts, type, case_id, actor, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            event.id,
            event.ts,
            event.type,
            event.case_id,
            event.actor,
            json.dumps(event.payload),
        ),
    )
    conn.commit()

    for callback in _subscribers.get(event.type, []):
        callback(event)

    return event


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        ts=row["ts"],
        type=row["type"],
        case_id=row["case_id"],
        actor=row["actor"],
        payload=json.loads(row["payload"]),
    )


def query_events(
    conn: sqlite3.Connection,
    *,
    case_id: str | None = None,
    type: str | None = None,
) -> list[Event]:
    """Query the log by case_id and/or type, ordered oldest-first."""
    clauses: list[str] = []
    params: list[str] = []
    if case_id is not None:
        clauses.append("case_id = ?")
        params.append(case_id)
    if type is not None:
        clauses.append("type = ?")
        params.append(type)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM event{where} ORDER BY ts ASC, rowid ASC", params
    ).fetchall()
    return [_row_to_event(r) for r in rows]


def replay(conn: sqlite3.Connection, *, case_id: str | None = None) -> list[Event]:
    """Full ordered replay of the log (optionally scoped to one case)."""
    return query_events(conn, case_id=case_id)
