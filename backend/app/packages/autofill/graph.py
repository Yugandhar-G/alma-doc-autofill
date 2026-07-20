"""Autofill graph: review_gate (interrupt) → populate → END.

The deterministic skeleton mirrors the screener's contract: fixed edges, no
LLM anywhere in this graph (extraction already happened at the boundary;
population is Playwright + read-back diff). What the graph adds over the old
HTTP-orchestrated flow is durability: the review pause checkpoints, so an
in-review run survives a backend restart and resumes on the same thread.
"""
import logging

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.packages.autofill.state import AutofillState
from app.population import populate_form  # module-level: test seam
from app.schemas import G28Data, PassportData

logger = logging.getLogger("yunaki.autofill.graph")


async def review_gate(state: AutofillState) -> dict:
    """Park for human review. The interrupt payload is what the reviewer
    edits; the resume value re-validates through the SAME schemas the
    extractor emits — an edit cannot smuggle in an invalid shape."""
    resume = interrupt(
        {
            "passport": state.passport_envelope.model_dump()
            if state.passport_envelope
            else None,
            "g28": state.g28_envelope.model_dump() if state.g28_envelope else None,
        }
    )
    resume = resume or {}
    passport = resume.get("passport")
    g28 = resume.get("g28")
    return {
        "passport": PassportData.model_validate(passport) if passport else None,
        "g28": G28Data.model_validate(g28) if g28 else None,
        "headed": resume.get("headed"),
    }


async def populate(state: AutofillState) -> dict:
    """Fill + read-back verify + artifact capture — the existing guardrailed
    engine, unchanged (allow-list selectors, nulls skipped, never submits)."""
    if state.passport is None and state.g28 is None:
        logger.info("populate skipped run=%s (reviewer approved nothing)", state.run_id)
        return {}
    report = await populate_form(state.passport, state.g28, headed=state.headed)
    return {"report": report}


def build_graph(checkpointer=None):
    """Compile the autofill graph. Checkpointer injected — tests use a temp
    saver, the API owns the real one (review must survive reloads)."""
    graph = StateGraph(AutofillState)
    graph.add_node("review_gate", review_gate)
    graph.add_node("populate", populate)
    graph.add_edge(START, "review_gate")
    graph.add_edge("review_gate", "populate")
    graph.add_edge("populate", END)
    return graph.compile(checkpointer=checkpointer)
