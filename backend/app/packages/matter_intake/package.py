"""The matter-intake (document chase) package export — installed via
app.registry.

Ships the chase graph as the package graph and mounts the ask-the-matter
research endpoint through router_factory. tool_grants records the firm-data
subset this package's agent may use (a documentation + config-lint signal;
the agent enforces it structurally through the granted registry at run time)."""
from app.kernel.package import PackageManifest, StageSpec, WorkflowPackage
from app.packages.matter_intake.chase import build_graph
from app.packages.matter_intake.router import router_factory
from app.packages.matter_intake.schemas import ChaseState

PACKAGE = WorkflowPackage(
    manifest=PackageManifest(
        package_id="matter_intake",
        version="1.0.0",
        title="Document Chase",
        description=(
            "Firm-data agent: classify document arrivals, reason about gaps "
            "against the case-type requirements registry (conditional gaps "
            "included), draft client chase messages → human review → recorded "
            "to firm memory. Reasons over firm records only; never sends."
        ),
        matter_types=("immigration",),
        stages=(
            StageSpec(id="classify", label="Classify arrivals", nodes=("classify_arrivals",)),
            StageSpec(id="reason", label="Reason about gaps", nodes=("reason_gaps",)),
            StageSpec(id="review", label="Review gaps", nodes=("chase_review",)),
            StageSpec(id="finalize", label="Record outcome", nodes=("finalize",)),
        ),
        interrupt_kinds=("chase_review",),
    ),
    state_model=ChaseState,
    build_graph=build_graph,
    router_factory=router_factory,
    tool_grants=frozenset({"list_matter_docs", "read_extraction", "recall_memory"}),
)
