"""Dual-consumption event router — CLAUDE_WORKPLAN.md §2 item 3/§2.6.

draft.created and escalation.raised are consumed TWO ways, deduplicated by event
id:

  (a) core.events.subscribe — fires synchronously inside emit() for events
      emitted IN THIS process (e.g. escalation "Send again" creates a draft here).
      Low latency, but the in-process pubsub does NOT cross process boundaries.

  (b) a ~2s poller over the core `event` table — the seam for events emitted by
      OTHER processes (Workstream B / dev_stub run separately). This is the only
      path that sees cross-process events.

Both paths feed ONE asyncio.Queue; the single consumer claims each event id in
`slack_seen_event` (atomic INSERT OR IGNORE) before handling it. So an event
seen by both the subscriber and the poller is posted exactly once — whichever
path reaches the claim first wins, the other is dropped. The subscriber callback
runs on the loop thread but only enqueues (via call_soon_threadsafe), never does
async I/O, so it's safe to fire from inside emit().
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import Awaitable, Callable

from core import events
from core.models import Event
from slack_agent import threads

logger = logging.getLogger("slack_agent.router")

Handler = Callable[[Event], Awaitable[None]]


class EventRouter:
    def __init__(
        self,
        conn: sqlite3.Connection,
        handlers: dict[str, Handler],
        *,
        poll_interval: float = 2.0,
    ) -> None:
        self.conn = conn
        self.handlers = handlers
        self.poll_interval = poll_interval
        self.queue: asyncio.Queue[Event] = asyncio.Queue()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task] = []

    # -- enqueue (thread-safe) --------------------------------------------- #

    def _enqueue(self, event: Event) -> None:
        if self.loop is None:
            self.queue.put_nowait(event)
            return
        self.loop.call_soon_threadsafe(self.queue.put_nowait, event)

    # -- path (a): in-process pubsub --------------------------------------- #

    def subscribe(self) -> None:
        for event_type in self.handlers:
            events.subscribe(event_type, self._enqueue)

    # -- path (b): cross-process poller ------------------------------------ #

    def poll_once(self) -> None:
        """Scan the event table past the high-water mark and enqueue new rows."""
        types = tuple(self.handlers)
        if not types:
            return
        placeholders = ",".join("?" * len(types))
        high_water = threads.get_high_water(self.conn)
        rows = self.conn.execute(
            f"SELECT rowid AS rid, id, ts, type, case_id, actor, payload "
            f"FROM event WHERE rowid > ? AND type IN ({placeholders}) ORDER BY rowid",
            (high_water, *types),
        ).fetchall()
        max_rid = high_water
        for row in rows:
            self._enqueue(
                Event(
                    id=row["id"],
                    ts=row["ts"],
                    type=row["type"],
                    case_id=row["case_id"],
                    actor=row["actor"],
                    payload=json.loads(row["payload"]),
                )
            )
            max_rid = max(max_rid, row["rid"])
        if max_rid > high_water:
            threads.set_high_water(self.conn, max_rid)

    async def dispatch(self, event: Event) -> None:
        """Claim (dedup) then handle. Idempotent across both consumption paths."""
        if not threads.claim_event(self.conn, event.id):
            logger.debug("event %s already handled — skipped", event.id)
            return
        handler = self.handlers.get(event.type)
        if handler is None:
            return
        try:
            await handler(event)
        except Exception:  # noqa: BLE001 - one bad event must not kill the loop
            logger.exception("handler failed for event %s (%s)", event.id, event.type)

    # -- lifecycle --------------------------------------------------------- #

    async def _poll_loop(self) -> None:
        while True:
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001
                logger.exception("poller iteration failed")
            await asyncio.sleep(self.poll_interval)

    async def _consume_loop(self) -> None:
        while True:
            event = await self.queue.get()
            await self.dispatch(event)

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._tasks = [
            asyncio.create_task(self._poll_loop()),
            asyncio.create_task(self._consume_loop()),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks = []
