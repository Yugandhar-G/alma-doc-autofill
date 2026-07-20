"""The autofill package export — installed via app.registry."""
from app.kernel.package import PackageManifest, StageSpec, WorkflowPackage
from app.packages.autofill.api import router_factory
from app.packages.autofill.graph import build_graph
from app.packages.autofill.state import AutofillState

PACKAGE = WorkflowPackage(
    manifest=PackageManifest(
        package_id="autofill",
        version="1.0.0",
        title="Document Autofill",
        description=(
            "Passport + G-28 extraction → human review → guardrailed form "
            "population with read-back verification and artifact capture."
        ),
        matter_types=("immigration",),
        stages=(
            StageSpec(id="review", label="Review extracted data", nodes=("review_gate",)),
            StageSpec(id="populate", label="Populate & verify", nodes=("populate",)),
        ),
        interrupt_kinds=("extraction_review",),
    ),
    state_model=AutofillState,
    build_graph=build_graph,
    router_factory=router_factory,
)
