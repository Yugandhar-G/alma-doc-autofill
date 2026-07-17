"""Screener graph: a deterministic skeleton whose nodes make schema-bound
Gemini calls. Edges are fixed; the only routing decisions are pure Python
over state and settings (whether web enrichment runs, whether the EB-1A
final-merits gate opens). No LLM ever chooses the path.

    START → compile_matrix → review_gate [interrupt: human edits matrix]
          → [verify_profile?]   tool-loop agent: web search + page fetch,
          │                     budgeted, transcript-audited
          → plan_assessments ─(Send fan-out)→ assess_one×N
          → merits_gate → [final_merits?] → verdict → profile_summary
          → assemble_report → END
"""
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.config import get_settings
from app.screener.criteria import EB1A_THRESHOLD, criteria_for, criteria_for_targets
from app.screener.nodes import (
    assemble_report,
    assess_one,
    compile_matrix,
    final_merits,
    profile_summary,
    review_gate,
    verdict,
    verify_profile,
)
from app.screener.state import AssessOneInput, ScreenerState


def route_verification(state: ScreenerState) -> str:
    """Pure function over settings + state: the verification agent runs only
    when enabled, a key is present, and there are reviewed claims to check."""
    settings = get_settings()
    if (
        settings.screener_web_enrichment
        and settings.gemini_api_key
        and state.matrix is not None
        and state.matrix.items
    ):
        return "verify_profile"
    return "plan_assessments"


async def plan_assessments(state: ScreenerState) -> dict:
    """Join point before the fan-out; the Send list is computed by the
    conditional edge below. Deterministic, no LLM."""
    return {}


def fan_out_assessments(state: ScreenerState) -> list[Send]:
    """One Send per criterion applicable to the targeted visa types."""
    return [
        Send("assess_one", AssessOneInput(criterion_id=spec.id, state=state))
        for spec in criteria_for_targets(list(state.visa_targets))
    ]


async def merits_gate(state: ScreenerState) -> dict:
    """Fan-in join for the parallel assessments. Deterministic, no LLM."""
    return {}


def route_merits(state: ScreenerState) -> str:
    """Kazarian step 2 runs only when EB-1A is targeted and step 1 (three
    criteria) is plausibly cleared — pure function, no LLM."""
    if "EB1A" not in state.visa_targets:
        return "verdict"
    eb1a_ids = {spec.id for spec in criteria_for("EB1A")}
    strong = sum(
        1
        for a in state.assessments
        if a.criterion_id in eb1a_ids and a.verdict in ("met", "likely")
    )
    return "final_merits" if strong >= EB1A_THRESHOLD else "verdict"


def build_graph(checkpointer=None):
    """Compile the screener graph. The checkpointer is injected so tests use
    a temp saver and the API owns the real (SQLite) one — the review_gate
    interrupt spans HTTP requests and must survive process reloads."""
    graph = StateGraph(ScreenerState)
    graph.add_node("compile_matrix", compile_matrix)
    graph.add_node("review_gate", review_gate)
    graph.add_node("verify_profile", verify_profile)
    graph.add_node("plan_assessments", plan_assessments)
    graph.add_node("assess_one", assess_one)
    graph.add_node("merits_gate", merits_gate)
    graph.add_node("final_merits", final_merits)
    graph.add_node("verdict", verdict)
    graph.add_node("profile_summary", profile_summary)
    graph.add_node("assemble_report", assemble_report)

    graph.add_edge(START, "compile_matrix")
    graph.add_edge("compile_matrix", "review_gate")
    graph.add_conditional_edges(
        "review_gate",
        route_verification,
        {"verify_profile": "verify_profile", "plan_assessments": "plan_assessments"},
    )
    graph.add_edge("verify_profile", "plan_assessments")
    graph.add_conditional_edges("plan_assessments", fan_out_assessments, ["assess_one"])
    graph.add_edge("assess_one", "merits_gate")
    graph.add_conditional_edges(
        "merits_gate", route_merits, {"final_merits": "final_merits", "verdict": "verdict"}
    )
    graph.add_edge("final_merits", "verdict")
    graph.add_edge("verdict", "profile_summary")
    graph.add_edge("profile_summary", "assemble_report")
    graph.add_edge("assemble_report", END)
    return graph.compile(checkpointer=checkpointer)
