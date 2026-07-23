"""Shared fixtures for Workstream A tests — no network, fake Bolt client.

The handoff agent is exercised with a FAKE kernel tool-loop that dispatches a
scripted sequence of tool calls through the REAL ToolRegistry (mirroring
tests/gmail_agent/conftest.py): the actual tool closures run, create rows, set
the terminal decision, and record into the transcript — so the whole
create/ask/emit/reply path is tested for real without deepagents or Gemini.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from agents import harness
from core import events
from core.db import connect_and_init
from slack_agent import approvals, senders, threads


@pytest.fixture()
def db(tmp_path) -> Iterator[sqlite3.Connection]:
    """Fresh core DB + slack_agent aux tables, subscribers/senders cleared, and
    the harness seams saved/restored so a scripted loop never leaks."""
    conn = connect_and_init(str(tmp_path / "test.db"))
    threads.ensure_tables(conn)
    harness.ensure_tables(conn)
    events.clear_subscribers()
    senders.clear()
    _saved = (harness.run_tool_loop, harness.make_agent_model, harness.MAX_TOOL_CALLS)
    try:
        yield conn
    finally:
        events.clear_subscribers()
        senders.clear()
        harness.run_tool_loop, harness.make_agent_model, harness.MAX_TOOL_CALLS = _saved
        conn.close()


class FakeSlackClient:
    """Records Slack Web API calls instead of hitting the network."""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.views: list[dict[str, Any]] = []
        # Thread-history seam: settable replies + a record of every fetch call.
        self.thread_replies: list[dict[str, Any]] = []
        self.replies_calls: list[dict[str, Any]] = []
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

    async def conversations_replies(self, **kwargs: Any) -> dict[str, Any]:
        self.replies_calls.append(kwargs)
        return {"messages": self.thread_replies}


@pytest.fixture()
def slack() -> FakeSlackClient:
    return FakeSlackClient()


@pytest.fixture()
def run():
    """Run a coroutine to completion without pytest-asyncio."""
    return lambda coro: asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Scripted model + fake kernel tool loop (real tools, no deepagents)
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
    """Install the fake loop and a scripted-model factory. Returns a setter for
    the script the None-model path will 'decide'; direct run_handoff callers may
    also pass model=ScriptModel(script) themselves."""

    def _set_script(script: list[tuple[str, dict]]) -> None:
        harness.run_tool_loop = fake_run_tool_loop
        harness.make_agent_model = lambda settings, live=False: ScriptModel(script)

    harness.run_tool_loop = fake_run_tool_loop
    return _set_script


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def approve_and_wait(db, slack, draft_id: str, **kwargs: Any) -> dict[str, Any]:
    """Drive approvals.approve (which offloads the work to a background task)
    and await that task to completion, returning its result. Runs the schedule
    and the awaited task on ONE event loop so the task actually executes."""

    async def _scenario() -> dict[str, Any]:
        task = await approvals.approve(db, slack, draft_id, **kwargs)
        return await task

    return asyncio.run(_scenario())
