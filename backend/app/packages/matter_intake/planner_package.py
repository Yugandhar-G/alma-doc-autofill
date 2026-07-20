"""The matter-planner package export — installed via app.registry.

The planner ships as its own package (second WorkflowPackage in this directory
tree, per the one-graph-per-package contract): it investigates the matter and
queues the next workflows for a human to approve. Its interrupt is plan_review;
its graph is the planner graph. No router of its own — ask-the-matter rides
matter_intake's router_factory."""
from app.kernel.package import PackageManifest, StageSpec, WorkflowPackage
from app.packages.matter_intake.planner import build_graph
from app.packages.matter_intake.schemas import PlannerState

PACKAGE = WorkflowPackage(
    manifest=PackageManifest(
        package_id="matter_planner",
        version="1.0.0",
        title="Matter Planner",
        description=(
            "Firm-data agent: investigate a matter, propose which installed "
            "workflows to run next (code disposes uninstalled / mismatched "
            "steps and fabricated missing-inputs) → human review → queue the "
            "approved runs. Queues only; the shell starts each queued run."
        ),
        matter_types=("immigration",),
        stages=(
            StageSpec(id="investigate", label="Investigate matter", nodes=("investigate",)),
            StageSpec(id="propose", label="Propose plan", nodes=("propose_plan",)),
            StageSpec(id="review", label="Review plan", nodes=("plan_review",)),
            StageSpec(id="enact", label="Queue runs", nodes=("enact",)),
        ),
        interrupt_kinds=("plan_review",),
    ),
    state_model=PlannerState,
    build_graph=build_graph,
    tool_grants=frozenset(
        {"list_matter_docs", "read_extraction", "search_matter_corpus", "recall_memory"}
    ),
)
