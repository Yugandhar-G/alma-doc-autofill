"""Offline fixtures for the Gmail agent — no network, no Gemini, no deepagents.

The email brain is exercised with a FAKE tool-loop that dispatches a scripted
sequence of tool calls through the REAL kernel ToolRegistry (mirroring the
matter_intake scripted-model pattern): the actual tool closures run, record into
the transcript, and set the terminal decision, so the deterministic audit + draft
path are tested for real without deepagents or Gemini installed.
"""

from __future__ import annotations

import asyncio
import base64
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from agents import harness
from core import events
from core.db import connect_and_init
from gmail_agent import config, state


# --------------------------------------------------------------------------- #
# DB + seam isolation
# --------------------------------------------------------------------------- #

@pytest.fixture()
def db(tmp_path) -> Iterator[sqlite3.Connection]:
    conn = connect_and_init(str(tmp_path / "test.db"))
    state.ensure_tables(conn)
    harness.ensure_tables(conn)
    events.clear_subscribers()
    _saved = (harness.run_tool_loop, harness.make_agent_model, harness.MAX_TOOL_CALLS)
    try:
        yield conn
    finally:
        events.clear_subscribers()
        harness.run_tool_loop, harness.make_agent_model, harness.MAX_TOOL_CALLS = _saved
        conn.close()


@pytest.fixture()
def run():
    return lambda coro: asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Scripted model + fake tool loop (real tools, no deepagents)
# --------------------------------------------------------------------------- #

class ScriptModel:
    """Carries a scripted tool-call sequence: list of (tool_name, args)."""

    def __init__(self, script: list[tuple[str, dict]]) -> None:
        self.script = script


async def fake_run_tool_loop(*, model, task_prompt, tools, budget, ctx, live=False, trace_name=""):
    """Dispatch the model's scripted tool calls through the real registry,
    honoring the budget exactly like the kernel's tool bridge does."""
    for name, args in getattr(model, "script", []):
        if ctx.transcript.tool_calls >= budget.max_tool_calls:
            break
        ctx.transcript.tool_calls += 1
        await tools.dispatch(name, args, ctx)
    return ctx.transcript


@pytest.fixture()
def wire_agent(db):
    """Install the fake loop and a scripted-model factory. Returns a setter that
    takes the script the (stubbed) model will 'decide'."""

    def _set_script(script: list[tuple[str, dict]]) -> None:
        harness.run_tool_loop = fake_run_tool_loop
        harness.make_agent_model = lambda settings, live=False: ScriptModel(script)

    harness.run_tool_loop = fake_run_tool_loop
    return _set_script


# --------------------------------------------------------------------------- #
# Fake Gmail API service
# --------------------------------------------------------------------------- #

def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def make_message(msg_id: str, thread_id: str, from_header: str, subject: str,
                 body: str, message_id_header: str = "<orig@mail>") -> dict:
    return {
        "id": msg_id,
        "threadId": thread_id,
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": from_header},
                {"name": "Subject", "value": subject},
                {"name": "Message-ID", "value": message_id_header},
            ],
            "body": {"data": b64(body)},
        },
    }


class _Req:
    def __init__(self, result: Any) -> None:
        self._result = result

    def execute(self) -> Any:
        return self._result


class _HistoryApi:
    def __init__(self, page: dict) -> None:
        self._page = page

    def list(self, **kwargs: Any) -> _Req:
        return _Req(self._page)


class _MessagesApi:
    def __init__(self, messages: dict, sent: list) -> None:
        self._messages = messages
        self._sent = sent

    def get(self, *, id: str, **kwargs: Any) -> _Req:  # noqa: A002
        return _Req(self._messages[id])

    def send(self, *, userId: str, body: dict) -> _Req:  # noqa: N803
        self._sent.append(body)
        return _Req({"id": "sent_1"})


class _ThreadsApi:
    def __init__(self, threads: dict) -> None:
        self._threads = threads

    def get(self, *, id: str, **kwargs: Any) -> _Req:  # noqa: A002
        return _Req(self._threads.get(id, {"messages": []}))


class _UsersApi:
    def __init__(self, svc: "FakeGmailService") -> None:
        self._svc = svc

    def history(self) -> _HistoryApi:
        return _HistoryApi(self._svc.history_page)

    def messages(self) -> _MessagesApi:
        return _MessagesApi(self._svc.messages, self._svc.sent)

    def threads(self) -> _ThreadsApi:
        return _ThreadsApi(self._svc.threads)


class FakeGmailService:
    def __init__(self, *, history_page: dict, messages: dict, threads: dict | None = None) -> None:
        self.history_page = history_page
        self.messages = messages
        self.threads = threads or {}
        self.sent: list[dict] = []

    def users(self) -> _UsersApi:
        return _UsersApi(self)


@pytest.fixture()
def cfg() -> config.GmailConfig:
    # Fictional fakes only — never a real address or project id.
    return config.GmailConfig(
        address="agent.demo@example.com",
        credentials_path=".secrets/gmail_credentials.json",
        token_path=".secrets/gmail_token.json",
        topic="projects/demo/topics/gmail",
        subscription="projects/demo/subscriptions/gmail-pull",
        adc_path="/tmp/adc.json",
    )


# --------------------------------------------------------------------------- #
# Seed helpers (fictional cast only)
# --------------------------------------------------------------------------- #

def seed_case_with_items(
    conn: sqlite3.Connection,
    *,
    email: str,
    labels: list[str],
    case_id: str = "case_demo",
    client_id: str = "client_demo",
    intake_id: str = "intake_demo",
) -> None:
    """A minimal case: one client + one intake + N missing mandatory items."""
    conn.execute(
        'INSERT INTO "case" (id, name, process_type, stage, created_at) '
        "VALUES (?, ?, ?, ?, ?)",
        (case_id, "Demo Case", "I-130", "USCIS-Case Opened", "2026-07-20T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO client (id, first_name, last_name, email, phone, whatsapp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (client_id, "Ravi", "Demo", email, None, None),
    )
    conn.execute(
        "INSERT INTO party (case_id, client_id, role) VALUES (?, ?, ?)",
        (case_id, client_id, "petitioner"),
    )
    conn.execute(
        "INSERT INTO intake (id, case_id, client_id, url, state, sent_at, last_client_activity_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (intake_id, case_id, client_id, "https://intake.demo.local/i/x", "sent",
         "2026-07-20T00:00:00+00:00", None),
    )
    for seq, label in enumerate(labels, start=1):
        conn.execute(
            "INSERT INTO checklist_item (id, intake_id, seq, label, mandatory_to_file, state) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (f"chk_{seq}", intake_id, seq, label, 1, "missing"),
        )
    conn.commit()
