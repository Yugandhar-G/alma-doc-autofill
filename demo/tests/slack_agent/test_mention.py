"""@yunaki mention surface: filtering, thread-case scoping, end-to-end draft
flow with a scripted model. Also pins the listener/mention collision fix:
a mention in the cases channel must NOT be parsed as a case handoff."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

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
    post = slack.posts[-1]
    assert post["thread_ts"] == "5.0" and post["text"] == reply


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


def test_case_context_names_thread_case(db) -> None:
    case_id = seed(db)
    ctx = mention._case_context(db, case_id)
    assert "Ravi Kumar / Mei Lin" in ctx and case_id in ctx
    assert "not inside a known case thread" in mention._case_context(db, None)
