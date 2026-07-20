"""The screener package export — installed via app.registry.

The screener keeps its legacy session API (mounted directly in create_app,
retired in Phase C1); the package export makes it visible to GET
/api/packages and gives the kernel its manifest/state/graph contract.
"""
from app.kernel.package import PackageManifest, StageSpec, WorkflowPackage
from app.screener.graph import build_graph
from app.screener.state import ScreenerState

PACKAGE = WorkflowPackage(
    manifest=PackageManifest(
        package_id="screener",
        version="1.0.0",
        title="O-1A / EB-1A Eligibility Screener",
        description=(
            "Evidence matrix compilation → human review → budgeted web "
            "verification agent → per-criterion assessment → citation-audited "
            "report. Decision support only."
        ),
        matter_types=("immigration",),
        stages=(
            StageSpec(id="compile", label="Compile evidence", nodes=("compile_matrix",)),
            StageSpec(id="review", label="Review claims", nodes=("review_gate",)),
            StageSpec(id="verify", label="Verify online", nodes=("verify_profile",)),
            StageSpec(
                id="assess",
                label="Assess criteria",
                nodes=("plan_assessments", "assess_one", "merits_gate", "final_merits"),
            ),
            StageSpec(
                id="report",
                label="Verdict & report",
                nodes=("verdict", "profile_summary", "assemble_report"),
            ),
        ),
        interrupt_kinds=("matrix_review",),
    ),
    state_model=ScreenerState,
    build_graph=build_graph,
    tool_grants=frozenset({"search_web", "fetch_page"}),
)
