"""Kernel deep-agent engine — deepagents-backed bounded tool loop.

Agentic where it matters, code-owned where it counts:
- deepagents (LangChain) OWNS THE LOOP: model turns, tool routing, planning
  (write_todos), context summarization. The MODEL decides what to call, with
  which arguments, and when it has seen enough.
- CODE owns the tool registry (allow-list), the call budget, the turn cap
  (langgraph recursion_limit), and the transcript — the deterministic ground
  truth that post-hoc audits run against. Budget exhaustion feeds the model a
  plain refusal string from inside the tool bridge; the recursion limit
  hard-stops the graph regardless of what the model wants next.

deepagents' filesystem / execute / subagent surfaces are structurally removed
via a HarnessProfile (grants are structural: an agent can only ever choose
among the tools its registry granted). Structured distillation of the
transcript stays on the direct Gemini path (app.kernel.llm) — response_schema
discipline is not negotiable there.

Decision log: hand-rolled loop replaced with deepagents on user instruction
(2026-07-19); see docs/agent-usage-log.md.
"""
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from google.genai import types as genai_types
from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel

from app.kernel.config import Settings
from app.kernel.observability import llm_generation, record_usage
from app.kernel.tools.registry import ToolContext, ToolRegistry, ToolSpec

logger = logging.getLogger("yunaki.kernel.agent")

# Structural tool discipline for every Gemini-backed deep agent in this
# process: no filesystem, no shell, no subagent spawning — kernel agents get
# exactly what their ToolRegistry grants, plus deepagents' planning todos
# (state-only, no external effect). Registered once at import.
register_harness_profile(
    "google_genai",
    HarnessProfile(
        excluded_tools=frozenset(
            {"ls", "read_file", "write_file", "edit_file", "glob", "grep",
             "execute", "task"}
        ),
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    ),
)


class AgentTranscript(BaseModel):
    """What actually happened — the deterministic ground truth for auditing."""

    seen_urls: list[str] = []
    fetched_urls: list[str] = []
    tool_calls: int = 0
    log: list[str] = []  # rendered steps for the caller's distillation call


@dataclass(frozen=True)
class AgentBudget:
    """Code-owned limits. max_tool_calls counts dispatched tools; max_turns
    counts model responses (a turn may carry several tool calls)."""

    max_tool_calls: int
    max_turns: int = 8


def make_agent_model(settings: Settings, live: bool = False) -> BaseChatModel:
    """Gemini chat model for the agent loop (module-level test seam in
    callers). Live runs include thought summaries for the activity feed."""
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.0,
        include_thoughts=live or None,
    )


_GENAI_JSON_TYPES = {
    genai_types.Type.STRING: "string",
    genai_types.Type.OBJECT: "object",
    genai_types.Type.INTEGER: "integer",
    genai_types.Type.NUMBER: "number",
    genai_types.Type.BOOLEAN: "boolean",
    genai_types.Type.ARRAY: "array",
}


def _json_schema(schema: genai_types.Schema) -> dict[str, Any]:
    """ToolSpec declarations are genai Schemas (the registry's native form);
    langchain tools take JSON schema. Deterministic structural translation."""
    out: dict[str, Any] = {"type": _GENAI_JSON_TYPES.get(schema.type, "string")}
    if schema.description:
        out["description"] = schema.description
    if schema.enum:
        out["enum"] = list(schema.enum)
    if schema.properties:
        out["properties"] = {
            name: _json_schema(sub) for name, sub in schema.properties.items()
        }
    if schema.required:
        out["required"] = list(schema.required)
    if schema.items is not None:
        out["items"] = _json_schema(schema.items)
    return out


class GrantEnforcementMiddleware(AgentMiddleware):
    """Structural tool discipline at the EXECUTION layer. The harness
    profile's excluded_tools only hides declarations from the model; the
    implementations stay in the tool node, so a hallucinated call to a
    non-granted tool would still execute. This middleware refuses it before
    it runs — grants are structural, not prompt-level. write_todos is
    allowed alongside the registry grants (state-only planning, no external
    effect)."""

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


def _bridge_tool(
    spec: ToolSpec, registry: ToolRegistry, budget: AgentBudget, ctx: ToolContext
) -> StructuredTool:
    """One granted tool as a langchain tool. The bridge owns the budget: an
    exhausted budget returns a refusal string without dispatching, exactly as
    the previous hand-rolled loop did."""
    transcript = ctx.transcript

    async def _run(**kwargs: Any) -> str:
        if transcript.tool_calls >= budget.max_tool_calls:
            return "BUDGET_EXHAUSTED: no tool calls left; write your findings."
        transcript.tool_calls += 1
        return await registry.dispatch(spec.name, kwargs, ctx)

    return StructuredTool(
        name=spec.name,
        description=spec.description,
        args_schema=_json_schema(spec.parameters),
        coroutine=_run,
    )


def _emit_thinking(message: AIMessage, ctx: ToolContext) -> None:
    """Surface reasoning blocks to the session-owner activity feed (the
    product's genuine feed channel — never the masked telemetry channel)."""
    content = message.content
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") not in ("thinking", "reasoning"):
            continue
        text = block.get("thinking") or block.get("reasoning") or block.get("text")
        if text:
            ctx.emit({"type": "model_thinking", "node": ctx.node, "text": text})


def _accumulate_usage(message: AIMessage, totals: dict[str, int]) -> None:
    usage = getattr(message, "usage_metadata", None) or {}
    totals["input"] += usage.get("input_tokens", 0) or 0
    totals["output"] += usage.get("output_tokens", 0) or 0
    totals["total"] += usage.get("total_tokens", 0) or 0


async def run_tool_loop(
    *,
    model: BaseChatModel,
    task_prompt: str,
    tools: ToolRegistry,
    budget: AgentBudget,
    ctx: ToolContext,
    live: bool = False,
    trace_name: str = "gemini.agent",
) -> AgentTranscript:
    """Run the deepagents loop; returns the transcript. The caller distills
    the transcript into its structured output and audits it.

    `ctx.transcript` must be the AgentTranscript this loop should record
    into; `ctx.emit` receives model_thinking events on live runs (tool_call /
    tool_result events are emitted by the tool implementations themselves,
    which own their payload shapes).
    """
    transcript: AgentTranscript = ctx.transcript
    agent = create_deep_agent(
        model=model,
        tools=[_bridge_tool(spec, tools, budget, ctx) for spec in tools],
        middleware=[
            GrantEnforcementMiddleware(frozenset(spec.name for spec in tools))
        ],
    )
    # One agent turn ≈ one model step + one tool step in the compiled graph;
    # the recursion limit is the code-owned hard stop for runaway loops.
    config = {"recursion_limit": budget.max_turns * 2}
    usage_totals = {"input": 0, "output": 0, "total": 0}

    with llm_generation(
        trace_name,
        model=getattr(model, "model", None) or type(model).__name__,
        metadata={"max_tool_calls": budget.max_tool_calls, "max_turns": budget.max_turns},
    ) as generation:
        try:
            async for update in agent.astream(
                {"messages": [HumanMessage(content=task_prompt)]},
                config=config,
                stream_mode="updates",
            ):
                for node_update in update.values():
                    for message in (node_update or {}).get("messages", []):
                        if not isinstance(message, AIMessage):
                            continue
                        if live:
                            _emit_thinking(message, ctx)
                        _accumulate_usage(message, usage_totals)
        except GraphRecursionError:
            logger.warning(
                "agent turn cap reached (max_turns=%s); proceeding with transcript",
                budget.max_turns,
            )
        record_usage(
            generation,
            SimpleNamespace(
                prompt_token_count=usage_totals["input"],
                candidates_token_count=usage_totals["output"],
                total_token_count=usage_totals["total"],
            ),
        )

    return transcript
