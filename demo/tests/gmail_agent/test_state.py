"""state — high-water forward-only + baseline None, and the dedup ledger."""

from __future__ import annotations

from gmail_agent import state


def test_high_water_none_then_forward_only(db):
    assert state.get_high_water(db) is None
    state.set_high_water(db, 100)
    assert state.get_high_water(db) == 100
    state.set_high_water(db, 50)  # never rewinds
    assert state.get_high_water(db) == 100
    state.set_high_water(db, 150)
    assert state.get_high_water(db) == 150


def test_seen_ledger_dedup(db):
    assert state.is_seen(db, "m1") is False
    assert state.mark_seen(db, "m1") is True   # first insert
    assert state.is_seen(db, "m1") is True
    assert state.mark_seen(db, "m1") is False  # already present


def test_watch_expiration_roundtrip(db):
    assert state.get_watch_expiration(db) is None
    state.set_watch_expiration(db, 123456789)
    assert state.get_watch_expiration(db) == 123456789
