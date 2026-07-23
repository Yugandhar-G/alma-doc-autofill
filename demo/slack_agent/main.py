"""Wiring + startup for the Slack agent — CLAUDE_WORKPLAN.md §2 item 1.

Bolt for Python, ASYNC, Socket Mode (AsyncApp + AsyncSocketModeHandler). Run
from demo/ with `python -m slack_agent.main`. Missing tokens ⇒ a clean startup
error and a non-zero exit (this is a standalone process — it fails loud, §1.4).

This module is the ONLY place that touches Bolt: it extracts the fields the core
logic needs from Bolt's callback payloads and delegates to the testable functions
in listener / approvals / escalations / status_command. Everything below the
Bolt boundary is exercised directly in tests without a live Slack connection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import sys

from core import drafts
from core.db import connect_and_init
from core.models import Event
from slack_agent import (
    approvals,
    escalations,
    listener,
    mention,
    senders,
    status_command,
    threads,
)
from slack_agent.router import EventRouter
from slack_agent.settings import MissingConfig, Settings, load

logger = logging.getLogger("slack_agent.main")


def _open_db() -> sqlite3.Connection:
    """Open the shared DB, ensure schema + aux tables, tune for concurrent use.

    WAL + a busy timeout let the poller read while Workstream B / dev_stub write
    from another process without spurious 'database is locked' errors.
    """
    conn = connect_and_init()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    threads.ensure_tables(conn)
    return conn


def _register(
    app, conn: sqlite3.Connection, settings: Settings, bot_user_id: str | None
) -> None:
    from slack_agent.blocks import trigger_line  # noqa: F401 (keeps import local)

    fallback = settings.channel_cases

    @app.event("message")
    async def _on_message(event, client, logger):  # noqa: ANN001
        # The bot engages on an explicit @yunaki tag (app_mention below). The
        # one exception: a reply INSIDE a thread the bot is already in — that's
        # a continuation of a conversation the user started with a tag, so it
        # should not need re-tagging. Everything else (untagged top-level posts,
        # threads the bot isn't in) is ignored.
        if event.get("bot_id") or event.get("subtype"):
            return
        thread_ts = event.get("thread_ts")
        if not thread_ts or thread_ts == event.get("ts"):
            return  # top-level post — requires a tag, handled by app_mention
        if f"<@{bot_user_id}>" in (event.get("text") or ""):
            return  # tagged reply — app_mention handles it, avoid double-fire
        channel = event.get("channel")
        if not threads.is_bot_thread(conn, channel, thread_ts):
            return  # not a thread the bot is participating in
        await mention.handle_mention(
            conn=conn,
            client=client,
            channel=channel,
            message_ts=event["ts"],
            thread_ts=thread_ts,
            text=event.get("text", ""),
        )

    @app.event("app_mention")
    async def _on_mention(event, client):  # noqa: ANN001
        if not mention.should_handle_mention(event):
            return
        ask = mention.strip_mention(event.get("text", ""))
        channel = event["channel"]
        root_ts = event.get("thread_ts") or event["ts"]
        # Route: a tagged message carrying case-handoff signal (a client email
        # or handoff language) goes to the handoff agent; everything else is a
        # question/status/draft ask for the mention agent.
        if listener.looks_like_handoff(ask):
            await listener.handle_handoff_message(
                conn=conn,
                client=client,
                channel=channel,
                message_ts=event["ts"],
                text=ask,
            )
        else:
            await mention.handle_mention(
                conn=conn,
                client=client,
                channel=channel,
                message_ts=event["ts"],
                thread_ts=event.get("thread_ts"),
                text=event.get("text", ""),
            )
        # Remember this thread so in-thread follow-ups continue without a re-tag.
        threads.mark_bot_thread(conn, channel, root_ts)

    @app.action("draft_approve")
    async def _approve(ack, body, client):  # noqa: ANN001
        await ack()
        await approvals.approve(
            conn,
            client,
            body["actions"][0]["value"],
            channel=body["channel"]["id"],
            message_ts=body["message"]["ts"],
        )

    @app.action("draft_reject")
    async def _reject(ack, body, client):  # noqa: ANN001
        await ack()
        await approvals.open_reject_modal(
            client,
            trigger_id=body["trigger_id"],
            draft_id=body["actions"][0]["value"],
            channel=body["channel"]["id"],
            message_ts=body["message"]["ts"],
        )

    @app.action("draft_edit")
    async def _edit(ack, body, client):  # noqa: ANN001
        await ack()
        await approvals.open_edit_modal(
            conn,
            client,
            trigger_id=body["trigger_id"],
            draft_id=body["actions"][0]["value"],
            channel=body["channel"]["id"],
            message_ts=body["message"]["ts"],
        )

    @app.view("draft_reject_submit")
    async def _reject_submit(ack, view, client):  # noqa: ANN001
        await ack()
        meta = json.loads(view["private_metadata"])
        reason = (
            view["state"]["values"]["reject_reason"]["reason"].get("value") or None
        )
        await approvals.submit_reject(
            conn,
            client,
            meta["draft_id"],
            reason,
            channel=meta["channel"],
            message_ts=meta["message_ts"],
        )

    @app.view("draft_edit_submit")
    async def _edit_submit(ack, view, client):  # noqa: ANN001
        await ack()
        meta = json.loads(view["private_metadata"])
        new_body = view["state"]["values"]["edit_body"]["body"]["value"]
        await approvals.submit_edit(
            conn,
            client,
            meta["draft_id"],
            new_body,
            channel=meta["channel"],
            message_ts=meta["message_ts"],
        )

    @app.action("escal_send_again")
    async def _escal_send(ack, body, client):  # noqa: ANN001
        await ack()
        await escalations.send_again(
            conn,
            client,
            body["actions"][0]["value"],
            channel=body["channel"]["id"],
            message_ts=body["message"]["ts"],
        )

    @app.action("escal_call_client")
    async def _escal_call(ack, body, client):  # noqa: ANN001
        await ack()
        await escalations.call_client(
            conn,
            client,
            body["actions"][0]["value"],
            channel=body["channel"]["id"],
            message_ts=body["message"]["ts"],
        )

    @app.action("escal_pause")
    async def _escal_pause(ack, body, client):  # noqa: ANN001
        await ack()
        await escalations.pause_chasing(
            conn,
            client,
            body["actions"][0]["value"],
            channel=body["channel"]["id"],
            message_ts=body["message"]["ts"],
        )

    @app.command("/yunaki")
    async def _status(ack, command, respond):  # noqa: ANN001
        await ack()
        text = (command.get("text") or "").strip()
        if text.lower().startswith("status"):
            text = text[len("status"):].strip()
        await respond(status_command.handle_status(conn, text))

    async def on_draft_created(event: Event) -> None:
        draft = drafts.get_draft(conn, event.payload.get("draft_id", ""))
        if draft is None:
            return
        await approvals.post_approval(conn, app.client, draft, fallback_channel=fallback)

    async def on_escalation(event: Event) -> None:
        await escalations.post_escalation(
            conn, app.client, event, fallback_channel=fallback
        )

    app._yunaki_router = EventRouter(  # stash so run() can start it
        conn,
        {"draft.created": on_draft_created, "escalation.raised": on_escalation},
        client=app.client,  # enables the router's intake.validated notify path
        fallback_channel=fallback,
    )


def _register_gmail_sender() -> None:
    """Soft-register the Gmail agent's sender if it's present and configured.

    gmail_agent is built in parallel by a separate owner. This is a SOFT
    dependency: if the import fails or build raises (not configured), we log one
    line and continue — the package works and every test passes with it absent.
    """
    try:
        from gmail_agent.sender import build_gmail_sender  # type: ignore

        gmail = build_gmail_sender()
    except Exception as exc:  # noqa: BLE001 - absence/misconfig is expected
        logger.info("gmail sender unavailable (%s) — continuing", type(exc).__name__)
        return
    senders.register_sender("client_email", gmail)
    senders.register_sender("status_reply", gmail)
    logger.info("gmail sender registered for client_email + status_reply")


async def _run(settings: Settings) -> None:
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
    from slack_bolt.app.async_app import AsyncApp

    conn = _open_db()
    app = AsyncApp(token=settings.bot_token)
    try:
        bot_user_id = (await app.client.auth_test())["user_id"]
    except Exception:  # noqa: BLE001 - degrade: mention/handoff overlap filter off
        logger.exception("auth_test failed; handoff listener won't filter mentions")
        bot_user_id = None
    _register(app, conn, settings, bot_user_id)
    _register_gmail_sender()

    router: EventRouter = app._yunaki_router
    router.subscribe()
    await router.start()

    logger.info("slack_agent online; watching channel %s", settings.channel_cases)
    handler = AsyncSocketModeHandler(app, settings.app_token)
    await handler.start_async()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        settings = load()
    except MissingConfig as exc:
        print(f"[slack_agent] STARTUP FAILED: {exc}", file=sys.stderr)
        return 1
    asyncio.run(_run(settings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
