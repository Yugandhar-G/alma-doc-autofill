"""Preflight graph: gather_packet → cross_checks → review_gate (interrupt) →
finalize → END.

Deterministic skeleton mirroring the autofill/screener contract: fixed edges,
no LLM anywhere (the whole battery is pure code). What the graph adds is
durability + a human gate: the audit pauses at review so a reviewer can approve
or edit the findings before the report is finalized, and that pause checkpoints
so it survives a backend restart.
"""
import logging

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.packages.preflight.checks import check_ids, run_checks
from app.packages.preflight.packet import gather_packet
from app.packages.preflight.schemas import PreflightFinding, PreflightReport
from app.packages.preflight.state import PreflightState

logger = logging.getLogger("yunaki.preflight.graph")


def _ok(findings: list[PreflightFinding]) -> bool:
    """A packet is filing-ok when it has zero critical findings."""
    return not any(f.severity == "critical" for f in findings)


def _report(case_type: str, findings: list[PreflightFinding], docs_examined: int) -> PreflightReport:
    return PreflightReport(
        case_type=case_type,
        findings=findings,
        checks_run=check_ids(),
        docs_examined=docs_examined,
        ok=_ok(findings),
    )


async def gather_packet_node(state: PreflightState) -> dict:
    """The seam node. Assembles the PacketView from this run's envelopes; a
    matter-scoped upgrade swaps the envelope source here and nothing downstream
    changes. Nothing to persist yet — cross_checks re-gathers deterministically
    (cheap, pure) so the packet never has to live in checkpointed state."""
    packet = gather_packet(state.envelopes, state.case_type)
    logger.info(
        "preflight gather run=%s docs=%d case=%s",
        state.run_id,
        len(packet.docs),
        state.case_type,
    )
    return {}


async def cross_checks(state: PreflightState) -> dict:
    """Run the whole deterministic battery → draft report."""
    packet = gather_packet(state.envelopes, state.case_type)
    findings = run_checks(packet)
    report = _report(state.case_type, findings, len(packet.docs))
    logger.info(
        "preflight checks run=%s findings=%d ok=%s",
        state.run_id,
        len(findings),
        report.ok,
    )
    return {"report": report}


async def review_gate(state: PreflightState) -> dict:
    """Park for human review with the draft report. The resume value is the
    approved/edited findings list; each finding re-validates through the SAME
    PreflightFinding schema — an edit cannot smuggle in an invalid shape. A
    resume without a findings list keeps the draft findings as approved."""
    draft = state.report
    resume = interrupt({"report": draft.model_dump() if draft else None})
    resume = resume or {}
    findings_in = resume.get("findings")
    if findings_in is None:
        approved = list(draft.findings) if draft else []
    else:
        approved = [PreflightFinding.model_validate(f) for f in findings_in]
    docs_examined = draft.docs_examined if draft else 0
    return {"report": _report(state.case_type, approved, docs_examined)}


async def finalize(state: PreflightState) -> dict:
    """Terminal: re-stamp ``ok`` from the approved findings authoritatively."""
    report = state.report
    if report is None:
        return {}
    return {"report": _report(state.case_type, list(report.findings), report.docs_examined)}


def build_graph(checkpointer=None):
    """Compile the preflight graph. Checkpointer injected — tests use a temp
    saver, the API owns the real one (review must survive reloads)."""
    graph = StateGraph(PreflightState)
    graph.add_node("gather_packet", gather_packet_node)
    graph.add_node("cross_checks", cross_checks)
    graph.add_node("review_gate", review_gate)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "gather_packet")
    graph.add_edge("gather_packet", "cross_checks")
    graph.add_edge("cross_checks", "review_gate")
    graph.add_edge("review_gate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
