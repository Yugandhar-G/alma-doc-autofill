"""The preflight package export — installed via app.registry.

Packet Pre-Flight v0: a deterministic pre-filing consistency audit. No LLM in
the graph — the whole battery is pure code. The flagship "cut your RFE rate"
wedge: catch identity mismatches, missing required documents, and (once the
edition registry is populated) stale form editions before a packet is filed.
"""
from app.kernel.package import PackageManifest, StageSpec, WorkflowPackage
from app.packages.preflight.api import router_factory
from app.packages.preflight.graph import build_graph
from app.packages.preflight.state import PreflightState

PACKAGE = WorkflowPackage(
    manifest=PackageManifest(
        package_id="preflight",
        version="1.0.0",
        title="Packet Pre-Flight",
        description=(
            "Deterministic pre-filing consistency audit: identity cross-checks, "
            "evidence completeness, and form-edition currency across a filing "
            "packet → human review → filing-readiness report. No LLM; pure code."
        ),
        matter_types=("immigration",),
        stages=(
            StageSpec(id="gather", label="Gather packet", nodes=("gather_packet",)),
            StageSpec(id="check", label="Run consistency checks", nodes=("cross_checks",)),
            StageSpec(id="review", label="Review findings", nodes=("review_gate",)),
            StageSpec(id="finalize", label="Finalize report", nodes=("finalize",)),
        ),
        interrupt_kinds=("preflight_review",),
    ),
    state_model=PreflightState,
    build_graph=build_graph,
    router_factory=router_factory,
)
