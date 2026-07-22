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
import os
import sqlite3
from typing import Any, Awaitable, Callable

from core import events
from core.models import Event
from slack_agent import blocks, threads

logger = logging.getLogger("slack_agent.router")

Handler = Callable[[Event], Awaitable[None]]

# Env read inline as a module constant: core.config is frozen and slack_agent's
# settings.py is outside this change's edit scope, so the caseworker handle used
# in the completeness notification is read directly from the environment here.
# No hardcoded Slack user id (§2.4) — a plain-text mention only; falls back to
# "Isaiah" (the design-partner paralegal) when SLACK_CASEWORKER_HANDLE is unset.
CASEWORKER_HANDLE = os.environ.get("SLACK_CASEWORKER_HANDLE") or "Isaiah"


class EventRouter:
    def __init__(
        self,
        conn: sqlite3.Connection,
        handlers: dict[str, Handler],
        *,
        poll_interval: float = 2.0,
        client: Any | None = None,
        fallback_channel: str | None = None,
    ) -> None:
        self.conn = conn
        # Copy so we can extend with router-owned handlers without mutating the
        # caller's dict.
        self.handlers = dict(handlers)
        self.poll_interval = poll_interval
        self.client = client
        self.fallback_channel = fallback_channel
        self.queue: asyncio.Queue[Event] = asyncio.Queue()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task] = []
        # Completeness notification (§2 "validate → if yes → tell Isaiah"): the
        # router owns this intake.validated handler itself so it rides the SAME
        # dual pubsub+poller dedupe path as draft.created. It needs a Slack
        # client to post; when none is supplied (e.g. a handlers-only unit
        # router) the subscription is simply not registered. Never clobbers a
        # caller-supplied intake.validated handler.
        if client is not None:
            self.handlers.setdefault("intake.validated", self._on_intake_validated)

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

    # -- router-owned handlers --------------------------------------------- #

    def _case_name(self, case_id: str) -> str:
        row = self.conn.execute(
            'SELECT name FROM "case" WHERE id = ?', (case_id,)
        ).fetchone()
        return row["name"] if row else case_id

    async def _on_intake_validated(self, event: Event) -> None:
        """Post the completeness notification when intake validation says done.

        complete=true  → post "✅ Intake complete …" into the case thread (or the
                          cases channel when the case is unmapped), mentioning the
                          caseworker in plain text.
        complete=false → nothing: the draft.created chase flow already owns the
                          "here's what's still missing" message. The event is
                          still claimed in dispatch(), so dedupe holds either way.
        """
        if not event.payload.get("complete"):
            return
        case_id = event.case_id or ""
        mapping = threads.get_thread(self.conn, case_id)
        if mapping:
            channel, thread_ts = mapping["channel"], mapping["thread_ts"]
        else:
            channel, thread_ts = self.fallback_channel, None
        await self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            blocks=blocks.intake_complete_blocks(
                self._case_name(case_id), CASEWORKER_HANDLE
            ),
            text="Intake complete — all mandatory items in",
        )
        logger.info("posted completeness notification for case=%s", case_id)

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
