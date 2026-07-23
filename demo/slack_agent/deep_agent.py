"""Bounded deepagents loop behind @yunaki mentions — Workstream A.

Ported from the kernel harness pattern (backend/app/kernel/agent.py), demo
grade, Anthropic-backed (the demo's one LLM vendor, §1.4):

- deepagents (LangGraph) OWNS THE LOOP: model turns, tool routing, planning.
  The MODEL decides which granted tool to call and when it has seen enough.
- CODE owns the grants, the call budget, and the turn cap. Grants are
  structural, not prompt-level: a HarnessProfile strips deepagents'
  filesystem / execute / subagent surfaces, and GrantEnforcementMiddleware
  refuses any tool call outside the granted set at the EXECUTION layer.
- The agent has NO send tool anywhere in the system. Outbound email exists
  only as a DraftAction the tools create (state=pending) — approval happens
  in Slack, execution in core.sendgate under LIVE_MODE (§4.1/§4.2).

No PII in logs: we log tool names and counts, never message bodies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.errors import GraphRecursionError

from core import config

logger = logging.getLogger("slack_agent.deep_agent")

_MODEL = "claude-sonnet-5"

# Structural tool discipline for every Anthropic-backed deep agent in this
# process: no filesystem, no shell, no subagent spawning — the mention agent
# gets exactly the tools agent_tools grants, plus deepagents' planning todos
# (state-only, no external effect). Registered once at import.
register_harness_profile(
    "anthropic",
    HarnessProfile(
        excluded_tools=frozenset(
            {"ls", "read_file", "write_file", "edit_file", "glob", "grep",
             "execute", "task"}
        ),
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    ),
)


@dataclass(frozen=True)
class AgentBudget:
    """Code-owned limits. max_tool_calls counts dispatched tools; max_turns
    counts model responses (a turn may carry several tool calls)."""

    max_tool_calls: int = 10
    max_turns: int = 8


@dataclass
class AgentRun:
    """What actually happened — names and counts only, never content (§4.4)."""

    tool_calls: int = 0
    tools_used: list[str] = field(default_factory=list)


class GrantEnforcementMiddleware(AgentMiddleware):
    """Refuse non-granted tool calls before they execute. The harness profile
    only hides declarations from the model; implementations stay in the tool
    node, so a hallucinated call would still run without this. write_todos is
    allowed alongside the grants (state-only planning, no external effect)."""

    def __init__(self, granted: frozenset[str]) -> None:
        super().__init__()
        self._granted = granted | {"write_todos"}

    def _refusal(self, request: ToolCallRequest) -> ToolMessage | None:
        name = request.tool_call.get("name", "")
        if name in self._granted:
            return None
        logger.warning("blocked non-granted tool call: %s", name)
        return ToolMessage(
            content=f"UNKNOWN_TOOL: {name}",
            tool_call_id=request.tool_call.get("id", ""),
            name=name,
            status="error",
        )

    def wrap_tool_call(self, request, handler):
        return self._refusal(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._refusal(request) or await handler(request)


def budgeted(
    run: AgentRun, budget: AgentBudget, name: str,
    fn: Callable[..., Awaitable[str]],
) -> Callable[..., Awaitable[str]]:
    """Wrap a tool coroutine so an exhausted budget returns a refusal string
    without dispatching — the code-owned side of the loop."""

    async def _run(**kwargs: Any) -> str:
        if run.tool_calls >= budget.max_tool_calls:
            return "BUDGET_EXHAUSTED: no tool calls left; write your answer now."
        run.tool_calls += 1
        run.tools_used.append(name)
        return await fn(**kwargs)

    return _run


def make_agent_model() -> BaseChatModel:
    """Claude chat model for the mention loop (module-level test seam)."""
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=_MODEL,
        api_key=config.get("ANTHROPIC_API_KEY"),
        # No temperature: sampling params are removed on claude-sonnet-5
        # (400: "`temperature` is deprecated for this model").
        max_tokens=4096,
    )


def _final_text(result: dict[str, Any]) -> str:
    """Extract the last AI message's text. Anthropic content may be a list of
    blocks; join the text ones."""
    messages = result.get("messages") or []
    if not messages:
        return ""
    content = messages[-1].content
    if isinstance(content, str):
        return content
    parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n".join(p for p in parts if p)


async def run_mention_agent(
    *,
    model: BaseChatModel,
    system_prompt: str,
    task_prompt: str,
    tools: list[BaseTool],
    run: AgentRun,
    budget: AgentBudget | None = None,
) -> str:
    """Run the bounded loop; return the agent's final reply text.

    `tools` must already be budget-wrapped via `budgeted` sharing `run`.
    Never raises to the caller: the turn cap degrades to an honest
    "out of turns" reply, any other failure to a plain unavailability line
    (fail loud in logs, safe text to Slack).
    """
    budget = budget or AgentBudget()
    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[
            GrantEnforcementMiddleware(frozenset(t.name for t in tools))
        ],
    )
    # One agent turn ≈ one model step + one tool step in the compiled graph.
    agent_config = {"recursion_limit": budget.max_turns * 2}
    try:
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=task_prompt)]}, config=agent_config
        )
    except GraphRecursionError:
        logger.warning(
            "mention agent turn cap reached (max_turns=%s, tool_calls=%s)",
            budget.max_turns,
            run.tool_calls,
        )
        return (
            "I ran out of turns before finishing. Here's where I stopped: "
            f"{run.tool_calls} tool call(s) made ({', '.join(run.tools_used) or 'none'}). "
            "Ask me again with a narrower question."
        )
    except Exception:  # noqa: BLE001 - loud in logs, safe text to Slack
        logger.exception("mention agent failed")
        return "Something went wrong while working on that — check the agent logs."

    text = _final_text(result)
    logger.info(
        "mention agent done: tool_calls=%d tools=%s reply_chars=%d",
        run.tool_calls,
        ",".join(run.tools_used) or "-",
        len(text),
    )
    return text or "I couldn't produce an answer for that."
