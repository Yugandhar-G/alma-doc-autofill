"""Shared fixtures — temp DB per test, subscriber isolation."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from core import events
from core.db import connect_and_init
from core.models import DraftAction, DraftGrounding, DraftTo


@pytest.fixture()
def db(tmp_path) -> Iterator[sqlite3.Connection]:
    """A fresh initialized SQLite DB on disk, torn down after each test."""
    path = str(tmp_path / "test.db")
    conn = connect_and_init(path)
    events.clear_subscribers()
    try:
        yield conn
    finally:
        events.clear_subscribers()
        conn.close()


@pytest.fixture()
def sample_draft() -> DraftAction:
    """A valid draft whose grounding.missing_items match its body (contract-clean)."""
    return DraftAction(
        case_id="case_ravi_mei_demo",
        kind="client_email",
        trigger="validation_incomplete",
        to=DraftTo(name="Ravi Kumar", channel_address="ravi.kumar.demo@example.com"),
        subject="A few documents still needed",
        body="Hi Ravi, we still need: Employment Verification letter.",
        grounding=DraftGrounding(
            missing_items=["Employment Verification letter"],
            case_state={"stage": "USCIS-Case Opened"},
            days_since_activity=4,
        ),
    )
