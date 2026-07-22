"""The always-on runner — CLAUDE_WORKPLAN.md §2 (Jul 22 scope change).

google-cloud-pubsub STREAMING PULL on GMAIL_PUBSUB_SUBSCRIPTION. No public URL,
no webhook, no polling of Gmail. Each Pub/Sub notification carries
{emailAddress, historyId}; we resume users.history.list from the stored
high-water mark, fetch each newly-added INBOX message, triage it, and run the
pipeline. The high-water mark advances (transactionally, forward-only) only AFTER
the whole batch processes; the gmail_seen_message ledger dedupes per message.

LOOP PREVENTION (critical): messages whose From address equals the agent's own
mailbox are skipped — no event, no draft — so replies the agent itself sends can
never re-trigger it.

ACK DISCIPLINE: ack after a notification is processed (including deterministic
skips); on any processing error, log loudly and nack so Pub/Sub redelivers.

The pubsub subscriber runs callbacks on background threads, so the DB connection
is opened check_same_thread=False and every DB touch is serialized under a lock
(flow control is also pinned to one message at a time). google-cloud-pubsub is
imported lazily inside run() so the rest of the package imports without it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import sys
import threading
from dataclasses import dataclass
from typing import Any

from agents import harness
from core.config import get_db_path
from core.db import init_schema
from gmail_agent import auth, config, email_agent, parsing, pipeline, state, watch

logger = logging.getLogger("gmail_agent.consumer")

# Serializes all DB access across pubsub callback threads.
_db_lock = threading.Lock()


@dataclass(frozen=True)
class NotificationSummary:
    baseline_set: bool
    considered: int
    processed: int
    drafts: int
    skipped_own: int
    skipped_nobody: int
    duplicates: int


def _open_db() -> sqlite3.Connection:
    """Open the shared DB for multi-threaded callback use.

    Mirrors core.db.get_connection but sets check_same_thread=False (pubsub
    delivers on background threads) and reuses core's DDL via init_schema — no
    /core edit, just the connect flags this consumer needs. WAL + busy_timeout
    keep it civil alongside the slack process on the same file.
    """
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    init_schema(conn)
    state.ensure_tables(conn)
    harness.ensure_tables(conn)
    return conn


def _make_thread_fetcher(service: Any, cfg: config.GmailConfig) -> Any:
    """A thread-history fetcher for the email agent's get_email_thread tool."""

    def fetch(thread_id: str) -> list[dict[str, Any]]:
        thread = (
            service.users()
            .threads()
            .get(
                userId=config.GMAIL_USER_ID,
                id=thread_id,
                format=config.MESSAGE_FORMAT,
            )
            .execute()
        )
        messages: list[dict[str, Any]] = []
        for raw in thread.get("messages", []):
            parsed = parsing.parse_message(raw)
            messages.append(
                {
                    "from": parsed.from_address,
                    "subject": parsed.subject,
                    "body": parsed.body,
                }
            )
        return messages

    return fetch


def _list_new_message_ids(
    service: Any, cfg: config.GmailConfig, start_history_id: int
) -> list[str]:
    """messagesAdded INBOX message ids since start_history_id, order-deduped."""
    ids: dict[str, None] = {}
    page_token: str | None = None
    while True:
        request = (
            service.users()
            .history()
            .list(
                userId=config.GMAIL_USER_ID,
                startHistoryId=start_history_id,
                historyTypes=[config.HISTORY_TYPE],
                labelId=config.INBOX_LABEL,
                pageToken=page_token,
            )
        )
        response = request.execute()
        for record in response.get("history", []):
            for added in record.get("messagesAdded", []):
                message = added.get("message") or {}
                message_id = message.get("id")
                if message_id:
                    ids[str(message_id)] = None
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return list(ids.keys())


def handle_message(
    conn: sqlite3.Connection, service: Any, cfg: config.GmailConfig, message_id: str
) -> str:
    """Fetch, filter, run the email agent, and run the pipeline for one message.

    Returns an outcome tag: 'dup' | 'own' | 'nobody' | 'processed' | 'drafted'.
    Marks the id seen ONLY on a terminal (non-error) outcome; a raised exception
    leaves it unseen so redelivery retries it.
    """
    if state.is_seen(conn, message_id):
        return "dup"

    message = (
        service.users()
        .messages()
        .get(
            userId=config.GMAIL_USER_ID,
            id=message_id,
            format=config.MESSAGE_FORMAT,
        )
        .execute()
    )
    inbound = parsing.parse_message(message)

    # Loop prevention: never react to our own outbound mail.
    if inbound.from_address and inbound.from_address.lower() == cfg.address.lower():
        logger.info("message=%s skipped: own address (loop prevention)", message_id)
        state.mark_seen(conn, message_id)
        return "own"

    if not inbound.body:
        logger.info("message=%s skipped: no plaintext/html body", message_id)
        state.mark_seen(conn, message_id)
        return "nobody"

    # The email brain: a real bounded tool-loop decides category + reply.
    thread_fetcher = _make_thread_fetcher(service, cfg)
    decision = asyncio.run(
        email_agent.run_email_agent(conn, inbound, thread_fetcher=thread_fetcher)
    )
    pipeline_result = pipeline.process(conn, inbound, decision)

    state.mark_seen(conn, message_id)
    return "drafted" if pipeline_result.draft_id else "processed"


def process_notification(
    conn: sqlite3.Connection,
    service: Any,
    cfg: config.GmailConfig,
    notification: dict[str, Any],
) -> NotificationSummary:
    """Process one Gmail push notification end-to-end.

    First notification ever (no baseline high-water): record the notification's
    historyId as the baseline and return — there is nothing to list before it.
    """
    notif_history_id = int(notification["historyId"])
    start = state.get_high_water(conn)

    if start is None:
        logger.warning(
            "no baseline high-water yet; setting baseline to historyId=%s "
            "(run `python -m gmail_agent.watch` to establish it deliberately)",
            notif_history_id,
        )
        state.set_high_water(conn, notif_history_id)
        return NotificationSummary(
            baseline_set=True,
            considered=0,
            processed=0,
            drafts=0,
            skipped_own=0,
            skipped_nobody=0,
            duplicates=0,
        )

    message_ids = _list_new_message_ids(service, cfg, start)

    processed = drafts = skipped_own = skipped_nobody = duplicates = 0
    for message_id in message_ids:
        outcome = handle_message(conn, service, cfg, message_id)
        if outcome == "dup":
            duplicates += 1
        elif outcome == "own":
            skipped_own += 1
        elif outcome == "nobody":
            skipped_nobody += 1
        elif outcome == "drafted":
            processed += 1
            drafts += 1
        else:  # 'processed'
            processed += 1

    # Advance the cursor AFTER the whole batch succeeded (forward-only).
    state.set_high_water(conn, notif_history_id)

    summary = NotificationSummary(
        baseline_set=False,
        considered=len(message_ids),
        processed=processed,
        drafts=drafts,
        skipped_own=skipped_own,
        skipped_nobody=skipped_nobody,
        duplicates=duplicates,
    )
    logger.info(
        "notification processed: considered=%d processed=%d drafts=%d "
        "own=%d nobody=%d dup=%d high_water=%d",
        summary.considered,
        summary.processed,
        summary.drafts,
        summary.skipped_own,
        summary.skipped_nobody,
        summary.duplicates,
        notif_history_id,
    )
    return summary


def maybe_renew_watch(
    conn: sqlite3.Connection, service: Any, cfg: config.GmailConfig
) -> None:
    """Re-register the watch when within 24h of expiry (or never registered)."""
    expiration = state.get_watch_expiration(conn)
    if not watch.needs_renewal(expiration):
        return
    logger.info("watch renewal due (expiration_ms=%s); re-registering", expiration)
    result = watch.register_watch(service, cfg)
    watch.persist_watch(conn, result)


def run(cfg: config.GmailConfig) -> None:
    """Open the streaming pull and block. Ctrl-C stops it cleanly."""
    from google.cloud import pubsub_v1

    conn = _open_db()
    service = auth.build_service()
    with _db_lock:
        maybe_renew_watch(conn, service, cfg)

    subscriber = pubsub_v1.SubscriberClient()
    flow_control = pubsub_v1.types.FlowControl(max_messages=1)

    def callback(message: Any) -> None:
        try:
            notification = json.loads(message.data)
            with _db_lock:
                process_notification(conn, service, cfg, notification)
                maybe_renew_watch(conn, service, cfg)
            message.ack()
        except Exception:  # noqa: BLE001 - fail loud, nack for redelivery
            logger.exception("notification processing failed; nacking for redelivery")
            message.nack()

    future = subscriber.subscribe(
        cfg.subscription, callback=callback, flow_control=flow_control
    )
    logger.info("gmail_agent consumer online; streaming pull on %s", cfg.subscription)
    try:
        future.result()
    except KeyboardInterrupt:
        logger.info("shutdown requested; cancelling streaming pull")
        future.cancel()
        future.result()
    finally:
        subscriber.close()
        conn.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        cfg = config.load()
    except config.MissingConfig as exc:
        print(f"[gmail_agent] STARTUP FAILED: {exc}", file=sys.stderr)
        return 1
    try:
        run(cfg)
    except auth.TokenMissing as exc:
        print(f"[gmail_agent] STARTUP FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
