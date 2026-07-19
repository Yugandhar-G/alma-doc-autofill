"""Generic bounded tool-loop (ReAct) agent — the kernel's deep-agent engine.

Agentic where it matters, code-owned where it counts:
- The MODEL decides what to call, with which arguments, and when it has seen
  enough.
- CODE owns the tool registry (allow-list), the call budget, the turn cap,
  and the transcript — the deterministic ground truth that post-hoc audits
  run against. Budget exhaustion feeds the model a plain refusal string; the
  loop hard-stops regardless of what the model wants next.

Extracted from the screener's verification agent (Phase 1); the screener now
adapts this loop with its own tools, prompt, and audit. Distillation and
auditing stay with the caller — different agents distill into different
schemas and audit against different ground truths.
"""
import logging
from dataclasses import dataclass
from typing import Any, Callable

from google.genai import types as genai_types
from pydantic import BaseModel

from app.kernel.observability import llm_generation, record_usage
from app.kernel.tools.registry import ToolContext, ToolRegistry

logger = logging.getLogger("yunaki.kernel.agent")


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


async def run_tool_loop(
    *,
    client: Any,
    model: str,
    task_prompt: str,
    tools: ToolRegistry,
    budget: AgentBudget,
    ctx: ToolContext,
    live: bool = False,
    trace_name: str = "gemini.agent",
) -> AgentTranscript:
    """Run the bounded loop; returns the transcript. The caller distills the
    transcript into its structured output and audits it.

    `ctx.transcript` must be the AgentTranscript this loop should record
    into; `ctx.emit` receives model_thinking events on live runs (tool_call /
    tool_result events are emitted by the tool implementations themselves,
    which own their payload shapes).
    """
    transcript: AgentTranscript = ctx.transcript
    config = genai_types.GenerateContentConfig(
        temperature=0.0,
        tools=[tools.declarations()],
        thinking_config=(
            genai_types.ThinkingConfig(include_thoughts=True) if live else None
        ),
    )
    contents: list[Any] = [task_prompt]

    for turn in range(budget.max_turns):
        with llm_generation(
            trace_name,
            model=model,
            metadata={"turn": turn, "tool_calls": transcript.tool_calls},
        ) as generation:
            response = await client.aio.models.generate_content(
                model=model, contents=contents, config=config
            )
            record_usage(generation, getattr(response, "usage_metadata", None))

        candidate = (response.candidates or [None])[0]
        if candidate is None or candidate.content is None:
            break
        parts = candidate.content.parts or []
        for part in parts:
            if part.text and getattr(part, "thought", False):
                ctx.emit({"type": "model_thinking", "node": ctx.node, "text": part.text})

        calls = [part.function_call for part in parts if part.function_call]
        if not calls or transcript.tool_calls >= budget.max_tool_calls:
            break

        contents.append(candidate.content)
        response_parts = []
        for fc in calls:
            if transcript.tool_calls >= budget.max_tool_calls:
                result = "BUDGET_EXHAUSTED: no tool calls left; write your findings."
            else:
                transcript.tool_calls += 1
                result = await tools.dispatch(fc.name, dict(fc.args or {}), ctx)
            response_parts.append(
                genai_types.Part.from_function_response(
                    name=fc.name, response={"result": result}
                )
            )
        contents.append(genai_types.Content(role="user", parts=response_parts))

    return transcript
