"""Planner agent offline: pure plan disposal, grant-block regression, and the
full investigate → propose_plan → plan_review (interrupt) → enact arc, asserting
enact QUEUES runs (does not execute them). Scripted model + faked distillation."""
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.kernel.agent import AgentBudget, AgentTranscript, run_tool_loop
from app.kernel.config import Settings
from app.kernel.tools.registry import ToolContext
from app.packages.matter_intake import loop, planner
from app.packages.matter_intake.schemas import PlannerState, PlanStep, ProposedPlan
from tests.matter_intake_util import bootstrap, make_store, scripted, tool_call_msg

_INSTALLED = {
    "preflight": frozenset({"immigration"}),
    "family": frozenset({"family_law"}),
    "autofill": frozenset(),  # empty = applies to any matter type
}


# --- Pure plan disposal ----------------------------------------------------
def test_dispose_drops_uninstalled_package() -> None:
    plan = ProposedPlan(steps=[PlanStep(package_id="ghost", reason="x")])
    kept, warnings = planner._dispose_plan(plan, [], _INSTALLED, "immigration", set(), set())
    assert kept == []
    assert any("not an installed package" in w for w in warnings)


def test_dispose_drops_matter_type_mismatch() -> None:
    plan = ProposedPlan(steps=[PlanStep(package_id="family", reason="x")])
    kept, warnings = planner._dispose_plan(plan, [], _INSTALLED, "immigration", set(), set())
    assert kept == []
    assert any("does not apply to matter type" in w for w in warnings)


def test_dispose_keeps_any_matter_type_package() -> None:
    plan = ProposedPlan(steps=[PlanStep(package_id="autofill", reason="x")])
    kept, _ = planner._dispose_plan(plan, [], _INSTALLED, "immigration", set(), set())
    assert [s.package_id for s in kept] == ["autofill"]


def test_dispose_strips_fabricated_missing_input_keeps_step() -> None:
    """A missing_input that is neither a seen ref nor a code-verified absence is
    stripped; the step itself survives with a trimmed input list."""
    plan = ProposedPlan(
        steps=[PlanStep(package_id="preflight", reason="x", missing_inputs=["g28", "made_up"])]
    )
    kept, warnings = planner._dispose_plan(
        plan, seen_refs=[], installed=_INSTALLED, matter_type="immigration",
        present_types={"passport"}, required_types={"passport", "g28"},
    )
    assert len(kept) == 1
    assert kept[0].missing_inputs == ["g28"]  # code-verified absent kept; fabricated stripped
    assert any("made_up" in w for w in warnings)


def test_dispose_keeps_missing_input_backed_by_seen_ref() -> None:
    plan = ProposedPlan(
        steps=[PlanStep(package_id="preflight", reason="x", missing_inputs=["doc-123"])]
    )
    kept, _ = planner._dispose_plan(
        plan, seen_refs=["doc-123"], installed=_INSTALLED, matter_type="immigration",
        present_types=set(), required_types=set(),
    )
    assert kept[0].missing_inputs == ["doc-123"]


# --- Grant-block regression (MANDATORY) ------------------------------------
async def test_planner_grants_block_non_granted_tools() -> None:
    turns = [
        tool_call_msg(
            ("write_file", {"file_path": "/tmp/x", "content": "y"}),
            ("fetch_page", {"url": "http://evil.example"}),
        ),
        AIMessage(content="done."),
    ]
    transcript = AgentTranscript()
    ctx = ToolContext(
        settings=Settings(_env_file=None), transcript=transcript,
        emit=lambda _e: None, node="investigate",
    )
    await run_tool_loop(
        model=scripted(*turns), task_prompt="p",
        tools=loop.granted_registry(planner._GRANTS),
        budget=AgentBudget(max_tool_calls=8), ctx=ctx,
    )
    assert transcript.tool_calls == 0


# --- Full graph interrupt/resume: enact queues runs only -------------------
@pytest.fixture
def graph_seams(tmp_path: Path, monkeypatch):
    store = make_store(tmp_path)
    monkeypatch.setattr(planner, "get_matter_store", lambda: store)
    monkeypatch.setattr(planner, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(loop, "make_client", lambda s: None)

    async def fake_call_gemini(client, model, prompt, wrapper, settings, **kwargs):
        assert wrapper is ProposedPlan
        return ProposedPlan(
            steps=[
                PlanStep(package_id="preflight", reason="run the pre-filing audit", missing_inputs=["g28"]),
                PlanStep(package_id="ghost_pkg", reason="not installed", missing_inputs=[]),
            ]
        )

    monkeypatch.setattr(loop, "call_gemini", fake_call_gemini)
    return store


async def test_planner_full_arc_queues_only_approved_installed_steps(graph_seams, monkeypatch) -> None:
    store = graph_seams
    scope, _ = await bootstrap(store)
    matter = await store.create_matter(scope, "immigration", "Petition")
    await store.add_document(scope, matter.id, "a" * 64, "passport", "p.pdf")

    turns = [
        tool_call_msg(("list_matter_docs", {"matter_id": matter.id})),
        AIMessage(content="Investigation complete."),
    ]
    monkeypatch.setattr(loop, "make_agent_model", lambda settings, live=False: scripted(*turns))

    graph = planner.build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "plan-1"}}
    state = PlannerState(
        run_id="run-1", firm_id=scope.firm_id, user_id=scope.user_id,
        matter_id=matter.id, matter_type="immigration", case_type="g28_filing",
    )
    result = await graph.ainvoke(state, config=config)

    # ghost_pkg disposed; preflight step kept with its code-verified g28 gap.
    payload = result["__interrupt__"][0].value
    assert [s["package_id"] for s in payload["steps"]] == ["preflight"]
    assert payload["steps"][0]["missing_inputs"] == ["g28"]
    assert any("ghost_pkg" in w for w in payload["warnings"])

    # No runs queued yet (enact hasn't run).
    assert await store.list_runs(scope, status="queued") == []

    # Approve unchanged → enact queues exactly one preflight run, does NOT run it.
    final = await graph.ainvoke(Command(resume={"steps": None}), config=config)
    queued = await store.list_runs(scope, status="queued")
    assert len(queued) == 1
    assert queued[0].package_id == "preflight"
    assert queued[0].status == "queued"  # queued, never executed
    assert final["report"]["queued_runs"][0]["package_id"] == "preflight"
