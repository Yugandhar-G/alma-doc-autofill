"""Agent harness — runs the kernel tool-loop and persists the transcript.

Wraps app.kernel.agent.run_tool_loop: builds the ToolContext + AgentTranscript,
applies the code-owned AgentBudget (constants below), runs the loop, and
persists the FULL transcript JSON to the aux table `agent_transcript`. The
transcript is both the demo's "show the agent working" artifact AND the audit
ground truth.

BUDGET (code-owned, per directive): max_tool_calls=12 (dispatched tools),
max_turns=8 (model responses). Enforced by the kernel: the tool bridge refuses
once the tool-call count hits the cap; the langgraph recursion limit
(max_turns*2) hard-stops the graph.

TEST SEAM: `run_tool_loop` and `make_agent_model` are module-level names,
resolved lazily from the kernel on first real use. Tests set fakes on this
module (mirrors matter_intake's `loop.make_agent_model` seam) so the suite runs
without deepagents/Gemini. `new_transcript()` returns the real AgentTranscript
when the kernel is importable, else a duck-compatible fallback (same fields),
so a faked loop still has something to record into on any interpreter.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger("agents.harness")

# Code-owned budget (directive constants).
MAX_TOOL_CALLS = 12
MAX_TURNS = 8

# Test seams — overwritten by tests; resolved lazily from the kernel otherwise.
run_tool_loop: Any = None
make_agent_model: Any = None


@dataclass
class _FallbackTranscript:
    """Duck-compatible stand-in for kernel AgentTranscript on interpreters
    without deepagents (fields the harness + audit touch)."""

    seen_urls: list[str] = field(default_factory=list)
    fetched_urls: list[str] = field(default_factory=list)
    seen_refs: list[str] = field(default_factory=list)
    tool_calls: int = 0
    log: list[str] = field(default_factory=list)


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the agent_transcript aux table. Idempotent. Namespaced to this
    agent layer (not a /core contract table)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS agent_transcript (
            id              TEXT PRIMARY KEY,
            case_id         TEXT,
            agent           TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            transcript_json TEXT NOT NULL
        );
        """
    )
    conn.commit()


def new_transcript() -> Any:
    """Real kernel AgentTranscript when importable, else the fallback."""
    try:
        from app.kernel.agent import AgentTranscript

        return AgentTranscript()
    except Exception:  # noqa: BLE001 - kernel/deepagents not present (e.g. 3.10)
        return _FallbackTranscript()


def _budget() -> Any:
    try:
        from app.kernel.agent import AgentBudget

        return AgentBudget(max_tool_calls=MAX_TOOL_CALLS, max_turns=MAX_TURNS)
    except Exception:  # noqa: BLE001
        return SimpleNamespace(max_tool_calls=MAX_TOOL_CALLS, max_turns=MAX_TURNS)


def _settings() -> Any:
    from app.kernel.config import Settings

    return Settings()


def _resolve_loop() -> Callable[..., Any]:
    global run_tool_loop
    if run_tool_loop is None:
        from app.kernel.agent import run_tool_loop as _rtl

        run_tool_loop = _rtl
    return run_tool_loop


def _resolve_model(model: Any, live: bool) -> Any:
    if model is not None:
        return model
    global make_agent_model
    if make_agent_model is None:
        from app.kernel.agent import make_agent_model as _mam

        make_agent_model = _mam
    return make_agent_model(_settings(), live)


def _serialize_transcript(transcript: Any) -> str:
    """Full transcript → JSON. Pydantic model (real) or dataclass (fallback)."""
    dump = getattr(transcript, "model_dump_json", None)
    if callable(dump):
        return dump()
    return json.dumps(
        {
            "seen_urls": list(getattr(transcript, "seen_urls", [])),
            "fetched_urls": list(getattr(transcript, "fetched_urls", [])),
            "seen_refs": list(getattr(transcript, "seen_refs", [])),
            "tool_calls": getattr(transcript, "tool_calls", 0),
            "log": list(getattr(transcript, "log", [])),
        },
        ensure_ascii=False,
    )


def persist_transcript(
    conn: sqlite3.Connection, transcript: Any, *, case_id: str | None, agent: str
) -> str:
    """Persist the full transcript JSON; returns the new transcript id."""
    transcript_id = f"tr_{uuid4().hex}"
    conn.execute(
        "INSERT INTO agent_transcript (id, case_id, agent, created_at, transcript_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            transcript_id,
            case_id,
            agent,
            datetime.now(timezone.utc).isoformat(),
            _serialize_transcript(transcript),
        ),
    )
    conn.commit()
    return transcript_id


async def run_agent(
    *,
    registry: Any,
    task_prompt: str,
    node: str,
    model: Any | None = None,
    emit: Callable[[dict], None] | None = None,
    live: bool = False,
    trace_name: str = "gemini.agent",
) -> Any:
    """Run the kernel tool-loop over `registry`; return the recorded transcript.

    The caller owns distillation of the terminal decision + the deterministic
    post-audit; this only runs the loop and hands back the transcript.
    """
    from app.kernel.tools.registry import ToolContext

    transcript = new_transcript()
    ctx = ToolContext(
        settings=_settings(),
        transcript=transcript,
        emit=emit or (lambda _event: None),
        node=node,
    )
    loop = _resolve_loop()
    await loop(
        model=_resolve_model(model, live),
        task_prompt=task_prompt,
        tools=registry,
        budget=_budget(),
        ctx=ctx,
        live=live,
        trace_name=trace_name,
    )
    logger.info(
        "agent loop done node=%s tool_calls=%s refs=%s",
        node,
        getattr(transcript, "tool_calls", "?"),
        len(getattr(transcript, "seen_refs", [])),
    )
    return transcript
