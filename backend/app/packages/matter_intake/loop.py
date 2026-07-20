"""Shared firm-data agent runner + distillation seam.

Every matter-intake agent is the same shape as the screener's agent: deepagents
runs the bounded tool loop over a firm-data grant subset (NO web tools), then a
DIRECT Gemini structured call distills the real transcript into a flat schema.

All three module-level seams live here so tests patch ONE place:
- ``make_agent_model`` — the langchain Gemini model for the loop,
- ``make_client`` / ``call_gemini`` — the direct structured-distillation path.

The firm-data grants are a strict subset of CORPUS_TOOLS resolved through
ToolRegistry.grant, which raises at build time if a package ever names a tool
that does not exist — grants are structural, caught early, never silently."""
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from app.config import Settings
from app.kernel.agent import (  # make_agent_model module-level: test seam
    AgentBudget,
    AgentTranscript,
    make_agent_model,
    run_tool_loop,
)
from app.kernel.llm import call_gemini, make_client  # module-level: test seams
from app.kernel.memory.service import MemoryService
from app.kernel.store.base import MatterStore, TenantScope
from app.kernel.tools.corpus import CORPUS_TOOLS
from app.kernel.tools.registry import ToolContext, ToolRegistry

logger = logging.getLogger("yunaki.matter_intake.loop")

# The full firm-data toolbox; each agent grants a subset. Built once.
_CORPUS_REGISTRY = ToolRegistry(CORPUS_TOOLS)


def granted_registry(grants: tuple[str, ...]) -> ToolRegistry:
    """A registry restricted to ``grants`` — structural tool discipline. Raises
    KeyError if any name is not a real corpus tool (a config bug, caught here)."""
    return _CORPUS_REGISTRY.grant(grants)


async def run_firm_agent(
    *,
    scope: TenantScope,
    store: MatterStore,
    settings: Settings,
    prompt: str,
    grants: tuple[str, ...],
    max_tool_calls: int,
    node: str,
    model: BaseChatModel | None = None,
) -> AgentTranscript:
    """Run the deepagents loop with a firm scope + firm-data grants, returning
    the transcript for the caller to distill and audit. ``emit`` is a no-op:
    these agents run on the (non-streaming) matter path; the SSE activity feed
    is a shell follow-up (the transcript still records every step)."""
    transcript = AgentTranscript()
    ctx = ToolContext(
        settings=settings,
        transcript=transcript,
        emit=lambda _event: None,
        node=node,
        scope=scope,
        matter_store=store,
        memory=MemoryService(store),
    )
    await run_tool_loop(
        model=model or make_agent_model(settings),
        task_prompt=prompt,
        tools=granted_registry(grants),
        budget=AgentBudget(max_tool_calls=max_tool_calls),
        ctx=ctx,
        trace_name=f"gemini.matter_intake.{node}",
    )
    logger.info(
        "firm agent done node=%s tool_calls=%d refs=%d",
        node, transcript.tool_calls, len(transcript.seen_refs),
    )
    return transcript


async def distill(
    settings: Settings, prompt: str, schema: type[BaseModel], *, trace_name: str
) -> Any:
    """Structured distillation of a transcript into a flat Gemini-safe schema.
    Single seam over the shared kernel call — response_schema discipline, retry,
    and PII-safe tracing all come from app.kernel.llm.call_gemini."""
    client = make_client(settings)
    return await call_gemini(
        client, settings.gemini_model, prompt, schema, settings, trace_name=trace_name
    )
