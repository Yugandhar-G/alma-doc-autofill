"""Event bus contract tests — enum enforcement (pydantic + DB) and pubsub."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from core import events
from core.models import Event


def test_unknown_event_type_rejected_by_pydantic():
    with pytest.raises(ValidationError):
        Event(type="totally.made_up", actor="agent:slack")


def test_unknown_event_type_rejected_by_db_check(db):
    # Bypass pydantic and prove the schema CHECK constraint is the second wall.
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO event (id, ts, type, case_id, actor, payload) "
            "VALUES ('evt_x', '2026-07-22T00:00:00+00:00', 'not.a.type', NULL, "
            "'agent:slack', '{}')"
        )


def test_bad_actor_rejected():
    with pytest.raises(ValidationError):
        Event(type="case.handoff_received", actor="robot")


def test_emit_persists_and_queryable(db):
    evt = Event(
        type="case.handoff_received",
        case_id="case_1",
        actor="agent:slack",
        payload={"parties": 2},
    )
    events.emit(db, evt)

    by_case = events.query_events(db, case_id="case_1")
    by_type = events.query_events(db, type="case.handoff_received")

    assert len(by_case) == 1
    assert len(by_type) == 1
    assert by_case[0].payload == {"parties": 2}


def test_subscribe_fires_synchronously_after_insert(db):
    received: list[Event] = []
    events.subscribe("draft.created", lambda e: received.append(e))

    events.emit(db, Event(type="draft.created", case_id="c1", actor="agent:validation"))
    events.emit(db, Event(type="intake.sent", case_id="c1", actor="agent:validation"))

    assert len(received) == 1
    assert received[0].type == "draft.created"


def test_replay_orders_by_ts(db):
    events.emit(db, Event(type="intake.sent", case_id="c1", actor="agent:validation"))
    events.emit(db, Event(type="intake.client_activity", case_id="c1", actor="client"))
    log = events.replay(db, case_id="c1")
    assert [e.type for e in log] == ["intake.sent", "intake.client_activity"]
