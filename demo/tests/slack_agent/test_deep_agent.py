"""Bounded deepagents loop: grants are structural, budget is code-owned.

All offline: a scripted fake chat model decides the 'model' turns, so these
tests exercise the REAL deepagents graph + middleware without any network.
"""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from slack_agent.deep_agent import (
    AgentBudget,
    AgentRun,
    budgeted,
    run_mention_agent,
    _final_text,
)


def _tool_call_msg(*calls):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{i}"}
            for i, (name, args) in enumerate(calls)
        ],
    )


class ScriptedChatModel(FakeMessagesListChatModel):
    """Scripted turns; tool binding is a no-op so the script alone decides
    what the 'model' calls."""

    def bind_tools(self, tools, **kwargs):
        return self


class EchoArgs(BaseModel):
    text: str = Field(description="text to echo")


def _echo_tool(run: AgentRun, budget: AgentBudget, calls: list[str]) -> StructuredTool:
    async def _echo(text: str) -> str:
        calls.append(text)
        return f"echo: {text}"

    return StructuredTool(
        name="echo",
        description="Echo the text back.",
        args_schema=EchoArgs,
        coroutine=budgeted(run, budget, "echo", _echo),
    )


def test_final_text_handles_block_content() -> None:
    result = {
        "messages": [
            AIMessage(content=[{"type": "text", "text": "part one"},
                               {"type": "tool_use", "id": "x", "name": "y", "input": {}},
                               {"type": "text", "text": "part two"}])
        ]
    }
    assert _final_text(result) == "part one\npart two"


def test_granted_tool_runs_and_reply_returned() -> None:
    run, budget, calls = AgentRun(), AgentBudget(), []
    model = ScriptedChatModel(
        responses=[
            _tool_call_msg(("echo", {"text": "hello"})),
            AIMessage(content="Done: hello"),
        ]
    )
    reply = asyncio.run(
        run_mention_agent(
            model=model,
            system_prompt="test",
            task_prompt="say hello",
            tools=[_echo_tool(run, budget, calls)],
            run=run,
            budget=budget,
        )
    )
    assert reply == "Done: hello"
    assert calls == ["hello"]
    assert run.tool_calls == 1
    assert run.tools_used == ["echo"]


def test_non_granted_tool_is_refused_not_executed() -> None:
    """A hallucinated call to a tool outside the grant set gets a refusal
    ToolMessage and the loop continues — grants are structural (§ kernel
    pattern), not prompt-level."""
    run, budget, calls = AgentRun(), AgentBudget(), []
    model = ScriptedChatModel(
        responses=[
            _tool_call_msg(("write_file", {"file_path": "/etc/x", "content": "pwn"})),
            AIMessage(content="ok, no tool then"),
        ]
    )
    reply = asyncio.run(
        run_mention_agent(
            model=model,
            system_prompt="test",
            task_prompt="try something not granted",
            tools=[_echo_tool(run, budget, calls)],
            run=run,
            budget=budget,
        )
    )
    assert reply == "ok, no tool then"
    assert calls == []          # implementation never executed
    assert run.tool_calls == 0  # budget untouched: refusal happens before dispatch


def test_budget_exhaustion_returns_refusal_string() -> None:
    run, budget, calls = AgentRun(), AgentBudget(max_tool_calls=1), []
    model = ScriptedChatModel(
        responses=[
            _tool_call_msg(("echo", {"text": "one"})),
            _tool_call_msg(("echo", {"text": "two"})),
            AIMessage(content="finished"),
        ]
    )
    reply = asyncio.run(
        run_mention_agent(
            model=model,
            system_prompt="test",
            task_prompt="spend the budget",
            tools=[_echo_tool(run, budget, calls)],
            run=run,
            budget=budget,
        )
    )
    assert reply == "finished"
    assert calls == ["one"]     # second dispatch refused inside the bridge
    assert run.tool_calls == 1


def test_turn_cap_degrades_to_honest_reply() -> None:
    """A model that never stops calling tools hits the recursion limit and the
    caller gets an 'out of turns' line, not an exception."""
    run, budget, calls = AgentRun(), AgentBudget(max_tool_calls=50, max_turns=2), []
    model = ScriptedChatModel(
        responses=[_tool_call_msg(("echo", {"text": f"n{i}"})) for i in range(20)]
    )
    reply = asyncio.run(
        run_mention_agent(
            model=model,
            system_prompt="test",
            task_prompt="loop forever",
            tools=[_echo_tool(run, budget, calls)],
            run=run,
            budget=budget,
        )
    )
    assert "ran out of turns" in reply
