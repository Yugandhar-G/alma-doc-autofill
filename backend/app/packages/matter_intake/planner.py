"""Planner agent + graph: investigate (agent) → propose_plan → plan_review
(interrupt) → enact.

- investigate: the deepagents firm-data loop; its transcript (log + seen_refs)
  is carried in state for the next node to distill.
- propose_plan: distill the transcript into a flat ProposedPlan, then CODE
  DISPOSES — strip any step whose package_id is not installed or whose manifest
  matter_types exclude this matter's type, and strip any missing_input that is
  neither backed by a seen ref nor a code-verified absence (the same anti-
  fabrication rule the chase agent applies to gaps).
- plan_review: a human gate carrying the disposed plan; resume returns the
  approved steps.
- enact: PURE CODE. For each approved step it QUEUES a WorkflowRun row via the
  matter store and stops there. v1 enact does NOT execute the queued runs:
  cross-package execution needs each target package's own initial state model,
  which the planner cannot mint safely from a plan step (it would have to guess
  each package's inputs — the exact fabrication this package exists to prevent).
  The shell starts a queued run through WorkflowService.start_run with a
  properly constructed initial state."""
import logging

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.config import get_settings
from app.kernel.store.base import TenantScope, get_matter_store  # module-level: seam
from app.packages.matter_intake import loop
from app.packages.matter_intake.prompts import planner_distill_prompt, planner_task_prompt
from app.packages.matter_intake.refs_audit import (
    is_code_verified_absence,
    normalize_kind,
    surviving_refs,
)
from app.packages.matter_intake.schemas import PlannerState, PlanStep, ProposedPlan
from app.packages.preflight.knowledge.requirements import requirements_for

logger = logging.getLogger("yunaki.matter_intake.planner")

_GRANTS = ("list_matter_docs", "read_extraction", "search_matter_corpus", "recall_memory")
_MAX_TOOL_CALLS = 8


def _scope(state: PlannerState) -> TenantScope:
    return TenantScope(firm_id=state.firm_id, user_id=state.user_id)


def _installed_matter_types() -> dict[str, frozenset[str]]:
    """package_id → the matter types its manifest applies to. Imported lazily to
    avoid an import cycle (app.registry imports this package)."""
    from app.registry import INSTALLED_PACKAGES

    return {
        p.manifest.package_id: frozenset(p.manifest.matter_types)
        for p in INSTALLED_PACKAGES
    }


def _catalog() -> str:
    from app.registry import INSTALLED_PACKAGES

    lines = [
        f"- {p.manifest.package_id} — {p.manifest.title} — {', '.join(p.manifest.matter_types) or 'any'}"
        for p in INSTALLED_PACKAGES
    ]
    return "\n".join(lines)


async def investigate(state: PlannerState) -> dict:
    """Run the firm-data loop; carry its transcript into state for propose_plan."""
    scope = _scope(state)
    store = get_matter_store()
    settings = get_settings()
    transcript = await loop.run_firm_agent(
        scope=scope, store=store, settings=settings,
        prompt=planner_task_prompt(state.matter_id, state.matter_type, _catalog(), _MAX_TOOL_CALLS),
        grants=_GRANTS, max_tool_calls=_MAX_TOOL_CALLS, node="investigate",
    )
    return {"transcript_log": list(transcript.log), "seen_refs": list(transcript.seen_refs)}


def _dispose_plan(
    plan: ProposedPlan,
    seen_refs: list[str],
    installed: dict[str, frozenset[str]],
    matter_type: str,
    present_types: set[str],
    required_types: set[str],
) -> tuple[list[PlanStep], list[str]]:
    """CODE DISPOSES: drop steps for uninstalled / matter-type-mismatched
    packages; strip missing_inputs that are neither a seen ref nor a code-
    verified absence. Pure, no mutation."""
    kept: list[PlanStep] = []
    warnings: list[str] = []
    for step in plan.steps:
        applies = installed.get(step.package_id)
        if applies is None:
            warnings.append(f"dropped step {step.package_id!r}: not an installed package")
            continue
        if applies and matter_type not in applies:
            warnings.append(
                f"dropped step {step.package_id!r}: does not apply to matter type {matter_type!r}"
            )
            continue
        inputs: list[str] = []
        for mi in step.missing_inputs:
            if surviving_refs([mi], seen_refs) or is_code_verified_absence(
                mi, required_types, present_types
            ):
                inputs.append(mi)
            else:
                warnings.append(
                    f"stripped missing_input {mi!r} on {step.package_id!r}: not seen and not a code-verified absence"
                )
        kept.append(step.model_copy(update={"missing_inputs": inputs}))
    return kept, warnings


async def propose_plan(state: PlannerState) -> dict:
    """Distill the carried transcript into a plan, then dispose it in code."""
    settings = get_settings()
    scope = _scope(state)
    store = get_matter_store()
    plan: ProposedPlan = await loop.distill(
        settings,
        planner_distill_prompt(state.matter_type, state.transcript_log, state.seen_refs),
        ProposedPlan,
        trace_name="gemini.matter_intake.propose_plan.distill",
    )
    docs = await store.list_documents(scope, state.matter_id)
    present_types = {normalize_kind(d.doc_type) for d in docs}
    reqs = requirements_for(state.case_type)
    required_types = {normalize_kind(r.doc_type) for r in (reqs.required if reqs else ())}
    steps, warnings = _dispose_plan(
        plan, state.seen_refs, _installed_matter_types(), state.matter_type, present_types, required_types
    )
    logger.info(
        "planner propose matter=%s proposed=%d kept=%d",
        state.matter_id, len(plan.steps), len(steps),
    )
    return {"steps": steps, "warnings": warnings}


async def plan_review(state: PlannerState) -> dict:
    """Human gate. Resume returns the approved steps (edits re-validate through
    PlanStep); a resume with no steps list keeps the disposed set."""
    resume = interrupt(
        {"steps": [s.model_dump() for s in state.steps], "warnings": list(state.warnings)}
    ) or {}
    approved_in = resume.get("steps")
    if approved_in is None:
        approved = list(state.steps)
    else:
        approved = [PlanStep.model_validate(s) for s in approved_in]
    return {"steps": approved}


async def enact(state: PlannerState) -> dict:
    """PURE CODE: queue a WorkflowRun row for each approved step. Does NOT
    execute them (see module docstring). Returns the report of queued run ids."""
    scope = _scope(state)
    store = get_matter_store()
    queued: list[dict] = []
    for step in state.steps:
        run = await store.create_run(scope, state.matter_id, step.package_id)
        queued.append({"run_id": run.id, "package_id": step.package_id, "status": run.status})
    logger.info("planner enact matter=%s queued=%d", state.matter_id, len(queued))
    report = {
        "matter_type": state.matter_type,
        "queued_runs": queued,
        "steps": [s.model_dump() for s in state.steps],
        "warnings": list(state.warnings),
    }
    return {"report": report}


def build_graph(checkpointer=None):
    """Compile the planner graph. Checkpointer injected — the plan-review gate
    must survive a reload."""
    graph = StateGraph(PlannerState)
    graph.add_node("investigate", investigate)
    graph.add_node("propose_plan", propose_plan)
    graph.add_node("plan_review", plan_review)
    graph.add_node("enact", enact)
    graph.add_edge(START, "investigate")
    graph.add_edge("investigate", "propose_plan")
    graph.add_edge("propose_plan", "plan_review")
    graph.add_edge("plan_review", "enact")
    graph.add_edge("enact", END)
    return graph.compile(checkpointer=checkpointer)
