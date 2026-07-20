"""The RFE-response package export — installed via app.registry.

RFE Response Assembler (Phase D3): parse an RFE notice → extract the deadline
and grounds → produce a cited response checklist + a code-assembled cover
structure → human review → feed the outcome to firm memory (kind="rfe"). Vision
+ one distillation call per run; deadline math and the citation audit are pure
code. The loop-closer for the Pre-Flight "cut your RFE rate" wedge.
"""
from app.kernel.package import PackageManifest, StageSpec, WorkflowPackage
from app.packages.rfe_response.api import router_factory
from app.packages.rfe_response.graph import build_graph
from app.packages.rfe_response.schemas import RfeResponseState

PACKAGE = WorkflowPackage(
    manifest=PackageManifest(
        package_id="rfe_response",
        version="1.0.0",
        title="RFE Response Assembler",
        description=(
            "Parse a USCIS Request-for-Evidence notice, extract the deadline and "
            "grounds, and assemble a cited response checklist + cover structure "
            "→ human review → firm-memory record. Vision + one distillation call; "
            "deadline math and citation audit are deterministic."
        ),
        matter_types=("immigration",),
        stages=(
            StageSpec(id="extract", label="Read notice", nodes=("extract_notice", "parse_grounds")),
            StageSpec(id="deadline", label="Check deadline", nodes=("deadline_check",)),
            StageSpec(id="checklist", label="Assemble checklist", nodes=("response_checklist",)),
            StageSpec(id="review", label="Review response plan", nodes=("review_gate",)),
            StageSpec(id="finalize", label="Finalize + record", nodes=("finalize",)),
        ),
        interrupt_kinds=("rfe_review",),
    ),
    state_model=RfeResponseState,
    build_graph=build_graph,
    router_factory=router_factory,
)
