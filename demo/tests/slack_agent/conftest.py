"""Shared fixtures for Workstream A tests — no network, fake Bolt client."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from core import events
from core.db import connect_and_init
from slack_agent import senders, threads
from slack_agent.handoff_parser import HandoffParse, HandoffParty


@pytest.fixture()
def db(tmp_path) -> Iterator[sqlite3.Connection]:
    """Fresh core DB + slack_agent aux tables, subscribers/senders cleared."""
    conn = connect_and_init(str(tmp_path / "test.db"))
    threads.ensure_tables(conn)
    events.clear_subscribers()
    senders.clear()
    try:
        yield conn
    finally:
        events.clear_subscribers()
        senders.clear()
        conn.close()


class FakeSlackClient:
    """Records Slack Web API calls instead of hitting the network."""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.views: list[dict[str, Any]] = []
        self._ts = 0

    async def chat_postMessage(self, **kwargs: Any) -> dict[str, Any]:
        self.posts.append(kwargs)
        self._ts += 1
        return {"ok": True, "ts": f"{self._ts}.000", "channel": kwargs.get("channel")}

    async def chat_update(self, **kwargs: Any) -> dict[str, Any]:
        self.updates.append(kwargs)
        return {"ok": True}

    async def views_open(self, **kwargs: Any) -> dict[str, Any]:
        self.views.append(kwargs)
        return {"ok": True}


@pytest.fixture()
def slack() -> FakeSlackClient:
    return FakeSlackClient()


@pytest.fixture()
def run():
    """Run a coroutine to completion without pytest-asyncio."""
    return lambda coro: asyncio.run(coro)


def make_parser(parse: HandoffParse):
    """Build a canned async parser returning a fixed HandoffParse."""

    async def _parse(_text: str) -> HandoffParse:
        return parse

    return _parse


# Canned parses used across tests (fictional cast only).
RAVI_MEI = HandoffParse(
    process_type="I-130 and I-485 One Step Marriage Based Green Cards",
    parties=[
        HandoffParty(
            role="petitioner",
            first_name="Ravi",
            last_name="Kumar",
            email="ravi.kumar.demo@example.com",
            phone=None,
        ),
        HandoffParty(
            role="beneficiary",
            first_name="Mei",
            last_name="Lin",
            email="mei.lin.demo@example.com",
            phone=None,
        ),
    ],
    available=True,
)

ALL_NULL = HandoffParse(process_type=None, parties=[], available=True)
