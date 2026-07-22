"""users.watch registration + renewal helper — CLAUDE_WORKPLAN.md §1.4 / §2.

CLI:  python -m gmail_agent.watch

Registers a Gmail push watch on the demo mailbox's INBOX to GMAIL_TOPIC, prints
the returned historyId + expiration, and stores the baseline historyId as the
consumer's high-water mark (so the first notification's history.list has a start
point). The watch expires ~every 7 days; `needs_renewal` lets the always-on
consumer re-register when it is within 24h of expiry (WATCH_RENEW_WITHIN_SECONDS).
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import time
from dataclasses import dataclass
from typing import Any

from core.db import connect_and_init
from gmail_agent import auth, config, state

logger = logging.getLogger("gmail_agent.watch")


@dataclass(frozen=True)
class WatchResult:
    history_id: int
    expiration_ms: int


def register_watch(service: Any, cfg: config.GmailConfig) -> WatchResult:
    """Call users.watch on the INBOX → GMAIL_TOPIC. Returns historyId+expiration.

    labelFilterBehavior=include + labelIds=[INBOX] scopes push notifications to
    inbound INBOX changes only.
    """
    body = {
        "topicName": cfg.topic,
        "labelIds": [config.INBOX_LABEL],
        "labelFilterBehavior": "include",
    }
    response = (
        service.users()
        .watch(userId=config.GMAIL_USER_ID, body=body)
        .execute()
    )
    history_id = int(response["historyId"])
    expiration_ms = int(response["expiration"])
    logger.info(
        "watch registered: historyId=%s expiration_ms=%s", history_id, expiration_ms
    )
    return WatchResult(history_id=history_id, expiration_ms=expiration_ms)


def persist_watch(conn: sqlite3.Connection, result: WatchResult) -> None:
    """Store the baseline high-water mark + expiration from a watch result.

    set_high_water never moves the mark backwards, so re-registering an active
    watch (renewal) does not rewind the consumer's cursor.
    """
    state.set_high_water(conn, result.history_id)
    state.set_watch_expiration(conn, result.expiration_ms)


def needs_renewal(expiration_ms: int | None, *, now_ms: int | None = None) -> bool:
    """True if the watch is unset or within WATCH_RENEW_WITHIN_SECONDS of expiry."""
    if expiration_ms is None:
        return True
    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    remaining_ms = expiration_ms - current_ms
    return remaining_ms <= config.WATCH_RENEW_WITHIN_SECONDS * 1000


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        cfg = config.load()
    except config.MissingConfig as exc:
        print(f"[gmail_agent.watch] STARTUP FAILED: {exc}", file=sys.stderr)
        return 1

    conn = connect_and_init()
    try:
        state.ensure_tables(conn)
        service = auth.build_service()
        result = register_watch(service, cfg)
        persist_watch(conn, result)
    except auth.TokenMissing as exc:
        print(f"[gmail_agent.watch] STARTUP FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(
        f"[gmail_agent.watch] watch active on INBOX → {cfg.topic}\n"
        f"  historyId (baseline high-water) = {result.history_id}\n"
        f"  expiration (epoch ms)           = {result.expiration_ms}\n"
        "Watch expires in ~7 days; the running consumer re-registers within 24h "
        "of expiry. Next: `python -m gmail_agent.main`."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
