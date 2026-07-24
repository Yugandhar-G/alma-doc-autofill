"""@yunaki mention surface: filtering, thread-case scoping, end-to-end draft
flow with a scripted model. Also pins the listener/mention collision fix:
a mention in the cases channel must NOT be parsed as a case handoff."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from core import events
from seed.seed_case import seed
from slack_agent import listener, mention, threads

BOT = "U0YUNAKI"


def _tool_call_msg(*calls):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{i}"}
            for i, (name, args) in enumerate(calls)
        ],
    )


class ScriptedChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class RecordingChatModel(ScriptedChatModel):
    """ScriptedChatModel that also records every HumanMessage it is handed, so a
    test can assert on the exact prompt the agent built (the base fake keeps no
    prompt log)."""

    captured: list = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        for msg in messages:
            if isinstance(msg, HumanMessage):
                self.captured.append(msg.content)
        return super()._generate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #

def test_strip_mention() -> None:
    assert mention.strip_mention(f"<@{BOT}> look at the case") == "look at the case"
    assert mention.strip_mention(f"<@{BOT}>") == ""


def test_should_handle_mention_rejects_bots_and_empty() -> None:
    assert mention.should_handle_mention({"text": f"<@{BOT}> hi", "user": "U1"})
    assert not mention.should_handle_mention(
        {"text": f"<@{BOT}> hi", "bot_id": "B1"}
    )
    assert not mention.should_handle_mention({"text": f"<@{BOT}>  "})


def test_listener_skips_bot_mentions_in_cases_channel() -> None:
    """Top-level '@yunaki ...' in #cases fires BOTH message and app_mention;
    the handoff listener must yield to the mention agent."""
    event = {
        "channel": "C1",
        "ts": "1.0",
        "text": f"<@{BOT}> look at the case we are working with",
        "user": "U1",
    }
    assert not listener.should_handle(event, "C1", BOT)
    # without the bot id (auth_test failed) behavior is unchanged:
    assert listener.should_handle(event, "C1", None)
    # a real handoff still passes:
    assert listener.should_handle({**event, "text": "New marriage case, Ravi"}, "C1", BOT)


# --------------------------------------------------------------------------- #
# handle_mention
# --------------------------------------------------------------------------- #

def _run_mention(db, client, model, *, text, thread_ts=None, monkeypatch=None):
    return asyncio.run(
        mention.handle_mention(
            conn=db,
            client=client,
            channel="C1",
            message_ts="9.0",
            thread_ts=thread_ts,
            text=text,
            model_factory=lambda: model,
        )
    )


def test_unavailable_without_api_key(db, slack, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reply = _run_mention(
        db, slack, None, text=f"<@{BOT}> look at the case"
    )
    assert reply is None
    assert "unavailable" in slack.posts[0]["text"]


def test_mention_answers_case_question_in_thread(db, slack, monkeypatch) -> None:
    """'@yunaki look at the case we are working with' inside the handoff
    thread: agent gets the thread's case in its prompt, calls the status tool,
    replies in the same thread."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    case_id = seed(db)
    threads.map_thread(db, case_id, "C1", "5.0")

    model = ScriptedChatModel(
        responses=[
            _tool_call_msg(("get_case_status", {"case_query": "Kumar"})),
            AIMessage(content="*Ravi Kumar / Mei Lin* is in stage intake."),
        ]
    )
    reply = _run_mention(
        db, slack, model,
        text=f"<@{BOT}> look at the case we are working with", thread_ts="5.0",
    )

    assert reply == "*Ravi Kumar / Mei Lin* is in stage intake."
    # Fallback loading: placeholder posts, gets DELETED (never edited), then
    # the reply arrives as a clean fresh post — nothing ever says (edited).
    assert "Thinking" in slack.posts[-2]["text"]
    assert slack.deletes and slack.deletes[-1]["ts"] == "1.000"
    post = slack.posts[-1]
    assert post["thread_ts"] == "5.0" and post["text"] == reply
    assert not slack.updates


def test_mention_draft_mail_creates_pending_draft_never_sends(
    db, slack, monkeypatch
) -> None:
    """'@yunaki draft a mail to client': the agent's draft tool leaves a
    pending DraftAction + draft.created event; nothing is sent."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    seed(db)
    captured: list = []
    events.subscribe("draft.created", captured.append)

    model = ScriptedChatModel(
        responses=[
            _tool_call_msg(
                (
                    "create_email_draft",
                    {
                        "case_query": "Kumar",
                        "recipient_name": "Mei Lin",
                        "recipient_email": "mei.lin.demo@example.com",
                        "subject": "Checking in",
                        "body": "Hi Mei, a quick update on your case.",
                    },
                )
            ),
            AIMessage(content="Draft ready — awaiting approval in this thread."),
        ]
    )
    reply = _run_mention(
        db, slack, model, text=f"<@{BOT}> draft a mail to the client"
    )

    assert "awaiting approval" in reply
    assert len(captured) == 1
    row = db.execute("SELECT state FROM draft").fetchone()
    assert row["state"] == "pending"
    assert db.execute("SELECT COUNT(*) c FROM message_sent").fetchone()["c"] == 0


def test_mention_create_case_then_drafts_invitation_never_sends(
    db, slack, monkeypatch
) -> None:
    """The full user story, offline: '@yunaki create a new case for Yugandhar
    Gopu …' → scripted create_case → scripted create_email_draft (portal link in
    the body) → reply that a draft is awaiting approval. Proves the case + stubs
    + firm case number exist, a pending draft was created, draft.created fired,
    and NOTHING was sent."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # No intake app in the test → make create_case's portal poll return instantly.
    from slack_agent import agent_tools

    monkeypatch.setattr(agent_tools, "POLL_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(agent_tools, "POLL_INTERVAL_SECONDS", 0.0)

    drafts: list = []
    events.subscribe("draft.created", drafts.append)

    reply_text = (
        "Case opened. A draft to *Yugandhar Gopu* at yugandhar.demo@example.com "
        "is waiting for your approval in this thread."
    )
    model = ScriptedChatModel(
        responses=[
            _tool_call_msg(
                (
                    "create_case",
                    {
                        "first_name": "Yugandhar",
                        "last_name": "Gopu",
                        "email": "yugandhar.demo@example.com",
                        "phone": "+1-555-0100",
                    },
                )
            ),
            _tool_call_msg(
                (
                    "create_email_draft",
                    {
                        "case_query": "Yugandhar",
                        "recipient_name": "Yugandhar Gopu",
                        "recipient_email": "yugandhar.demo@example.com",
                        "subject": "Welcome to Yew Legal — your intake link",
                        "body": (
                            "Hi Yugandhar, welcome aboard. Please start your "
                            "intake here: <PORTAL_LINK>. — Allison, Yew Legal"
                        ),
                    },
                )
            ),
            AIMessage(content=reply_text),
        ]
    )

    reply = _run_mention(
        db,
        slack,
        model,
        text=(
            f"<@{BOT}> create a new case for Yugandhar Gopu, phone +1-555-0100, "
            "email yugandhar.demo@example.com"
        ),
    )

    # The case exists with history stubs and a firm case number.
    from core.case_history import get_history

    case = db.execute('SELECT id, name FROM "case"').fetchone()
    assert case is not None and case["name"] == "Yugandhar Gopu"
    records = get_history(db, case["id"])
    assert len(records) == 1 and records[0].case_number

    # A pending draft was created and announced, but nothing was sent.
    assert reply == reply_text
    assert len(drafts) == 1
    assert db.execute("SELECT state FROM draft").fetchone()["state"] == "pending"
    assert db.execute("SELECT COUNT(*) c FROM message_sent").fetchone()["c"] == 0

    # Placeholder posted then deleted; the reply is a clean fresh post.
    assert "Thinking" in slack.posts[-2]["text"]
    assert slack.deletes
    post = slack.posts[-1]
    assert post["thread_ts"] == "9.0" and post["text"] == reply


def test_case_context_names_thread_case(db) -> None:
    case_id = seed(db)
    ctx = mention._case_context(db, case_id)
    assert "Ravi Kumar / Mei Lin" in ctx and case_id in ctx
    assert "not inside a known case thread" in mention._case_context(db, None)


# --------------------------------------------------------------------------- #
# thread_history — conversation memory via Slack replies
# --------------------------------------------------------------------------- #

def test_thread_history_formats_labels_strips_mentions_excludes_current(slack) -> None:
    """Mixed human/bot replies render oldest-first with the right speaker labels,
    mention tokens stripped, and the current ask excluded."""
    slack.thread_replies = [
        {"ts": "5.0", "text": f"<@{BOT}> what do we know about the Kumar case?", "user": "U1"},
        {"ts": "6.0", "text": "Ravi Kumar / Mei Lin — still in intake.", "bot_id": "B1"},
        {"ts": "7.0", "text": "thanks, one more thing", "subtype": "bot_message"},
        {"ts": "9.0", "text": "the live ask — must be excluded", "user": "U1"},
    ]

    history = asyncio.run(mention.thread_history(slack, "C1", "5.0", "9.0"))

    assert history is not None
    lines = history.split("\n")
    assert len(lines) == 3  # 4 replies minus the current (9.0)
    assert lines[0] == "Team member: what do we know about the Kumar case?"
    assert "<@" not in history  # mention token stripped
    assert lines[1].startswith("Yunaki: ")  # bot_id → Yunaki
    assert "Ravi Kumar / Mei Lin" in lines[1]
    assert lines[2].startswith("Yunaki: ")  # subtype bot_message → Yunaki
    assert "live ask" not in history  # current ts excluded
    # Fetched the thread root with the documented limit.
    assert slack.replies_calls == [{"channel": "C1", "ts": "5.0", "limit": 30}]


def test_thread_history_respects_caps(slack) -> None:
    """max_messages keeps the most recent; total_chars drops oldest first;
    per_message_chars truncates with a trailing ellipsis."""
    slack.thread_replies = [
        {"ts": f"{i}.0", "text": f"{i}: " + ("word " * 40), "user": "U1"}
        for i in range(1, 7)  # six messages, ts 1.0 .. 6.0
    ]

    # max_messages binds (char caps huge): keep newest 3, still oldest-first.
    capped = asyncio.run(
        mention.thread_history(
            slack, "C1", "root", "none",
            max_messages=3, per_message_chars=1000, total_chars=1_000_000,
        )
    )
    lines = capped.split("\n")
    assert len(lines) == 3
    assert lines[0].startswith("Team member: 4:")
    assert lines[-1].startswith("Team member: 6:")

    # total_chars + per_message truncation bind: each line ~34 chars, only the
    # two newest fit under 70, oldest-first.
    trimmed = asyncio.run(
        mention.thread_history(
            slack, "C1", "root", "none",
            max_messages=6, per_message_chars=20, total_chars=70,
        )
    )
    tlines = trimmed.split("\n")
    assert len(tlines) == 2
    assert all(line.endswith("…") for line in tlines)
    assert tlines[0].startswith("Team member: 5:")
    assert tlines[1].startswith("Team member: 6:")


def test_thread_history_api_failure_returns_none(slack) -> None:
    """A Slack API error never propagates — history degrades to None."""
    async def boom(**kwargs):
        raise RuntimeError("slack unavailable")

    slack.conversations_replies = boom
    assert asyncio.run(mention.thread_history(slack, "C1", "5.0", "9.0")) is None


def test_thread_history_none_when_only_current_message(slack) -> None:
    """A thread holding only the current ask yields no usable history."""
    slack.thread_replies = [{"ts": "9.0", "text": "just me", "user": "U1"}]
    assert asyncio.run(mention.thread_history(slack, "C1", "5.0", "9.0")) is None


def test_no_thread_skips_history_fetch(db, slack, monkeypatch) -> None:
    """A top-level mention (no thread_ts) must never call conversations_replies."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    seed(db)
    model = ScriptedChatModel(responses=[AIMessage(content="ok")])

    reply = _run_mention(db, slack, model, text=f"<@{BOT}> hello", thread_ts=None)

    assert reply == "ok"
    assert slack.replies_calls == []


def test_mention_followup_resolves_this_case_via_history(db, slack, monkeypatch) -> None:
    """The real transcript, fixed: a bare 'this case' follow-up in the same thread
    resolves because the prior turns are threaded into the prompt. Before the fix
    the stateless run answered 'I don't have a case name to work with yet'."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    case_id = seed(db)
    threads.map_thread(db, case_id, "C1", "5.0")

    # The thread so far: attorney named the Kumar case, Yunaki answered.
    slack.thread_replies = [
        {"ts": "5.0", "text": f"<@{BOT}> what do we know about the Kumar case?", "user": "U1"},
        {"ts": "6.0", "text": "Ravi Kumar / Mei Lin — still in intake, checklist pending.", "bot_id": "B1"},
    ]

    model = RecordingChatModel(
        responses=[
            _tool_call_msg(("get_case_status", {"case_query": "Kumar"})),
            AIMessage(content="*Ravi Kumar / Mei Lin* — intake, checklist pending."),
        ]
    )
    model.captured = []  # isolate from any prior instance's class-level list

    reply = asyncio.run(
        mention.handle_mention(
            conn=db,
            client=slack,
            channel="C1",
            message_ts="9.0",
            thread_ts="5.0",
            text="can you give me a brief what happened with this case",
            model_factory=lambda: model,
        )
    )

    # The prompt the model saw carries the history block and the case name, so a
    # bare "this case" ask has something to resolve against.
    assert model.captured, "model never received a HumanMessage"
    prompt = model.captured[0]
    assert "Conversation so far in this thread (oldest first):" in prompt
    assert "Kumar" in prompt
    assert "this case" in prompt  # the live ask, threaded in
    # The fix worked end to end: grounded reply as a clean fresh post.
    assert reply == "*Ravi Kumar / Mei Lin* — intake, checklist pending."
    post = slack.posts[-1]
    assert post["thread_ts"] == "5.0" and post["text"] == reply
    assert slack.deletes  # placeholder cleaned up, never edited


def test_native_thinking_status_when_enabled(db, slack, monkeypatch) -> None:
    """With the Agents & AI Apps toggle on, Slack renders the shimmer itself:
    set status -> work -> clear status; no placeholder message at all."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    seed(db)
    slack.native_status_enabled = True

    model = ScriptedChatModel(responses=[AIMessage(content="All quiet on this case.")])
    reply = _run_mention(db, slack, model, text=f"<@{BOT}> anything new?")

    assert reply == "All quiet on this case."
    assert [c["status"] for c in slack.status_calls] == ["is thinking...", ""]
    texts = [p["text"] for p in slack.posts]
    assert all("Thinking" not in t for t in texts)  # no placeholder in native mode
    assert not slack.deletes
