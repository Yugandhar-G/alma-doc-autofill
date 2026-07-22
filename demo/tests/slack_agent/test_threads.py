"""Aux-table persistence tests — dedup ledger, thread mapping, state."""

from __future__ import annotations

from slack_agent import threads


def test_claim_event_succeeds_once(db):
    assert threads.claim_event(db, "evt_1") is True
    assert threads.claim_event(db, "evt_1") is False
    assert threads.claim_event(db, "evt_2") is True


def test_thread_mapping_roundtrip_and_missing(db):
    assert threads.get_thread(db, "case_a") is None
    threads.map_thread(db, "case_a", "C1", "10.0")
    assert threads.get_thread(db, "case_a") == {"channel": "C1", "thread_ts": "10.0"}
    # Last write wins.
    threads.map_thread(db, "case_a", "C2", "20.0")
    assert threads.get_thread(db, "case_a") == {"channel": "C2", "thread_ts": "20.0"}


def test_high_water_defaults_and_persists(db):
    assert threads.get_high_water(db) == 0
    threads.set_high_water(db, 17)
    assert threads.get_high_water(db) == 17


def test_pause_flag(db):
    assert threads.is_paused(db, "case_a") is False
    threads.set_pause(db, "case_a", True)
    assert threads.is_paused(db, "case_a") is True
    threads.set_pause(db, "case_a", False)
    assert threads.is_paused(db, "case_a") is False
