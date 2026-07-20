"""Chase agent offline: pure gap audit, grant-block regression, and the full
classify → reason_gaps → chase_review (interrupt) → finalize arc on MemorySaver.
Scripted model + faked distillation — no network, no key."""
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.kernel.agent import AgentBudget, AgentTranscript, run_tool_loop
from app.kernel.config import Settings
from app.kernel.tools.registry import ToolContext
from app.packages.matter_intake import chase, loop
from app.packages.matter_intake.schemas import (
    ChaseDraft,
    ChaseState,
    GapFinding,
    GapFindings,
)
from tests.matter_intake_util import (
    FakeDocStore,
    bootstrap,
    make_store,
    scripted,
    tool_call_msg,
)


# --- Pure gap audit --------------------------------------------------------
async def test_audit_drops_fabricated_missing_doc_worst_class() -> None:
    """A 'missing' claim for a document that EXISTS is the worst defect class."""
    findings = GapFindings(findings=[GapFinding(doc_kind="passport", rationale="claims missing", refs=[])])
    kept, warnings = await chase._audit_gaps(
        findings, seen_refs=[], present_types={"passport"}, required_types={"passport", "g28"}
    )
    assert kept == []
    assert any("fabricated missing-document" in w for w in warnings)


async def test_audit_keeps_code_verified_absence_with_empty_refs() -> None:
    """Registry requires g28, store lacks it, model claims it uncited → survives
    via CODE-verified absence (not the model's word)."""
    findings = GapFindings(findings=[GapFinding(doc_kind="g28", rationale="required, absent", refs=[])])
    kept, warnings = await chase._audit_gaps(
        findings, seen_refs=[], present_types={"passport"}, required_types={"passport", "g28"}
    )
    assert [g.doc_kind for g in kept] == ["g28"]
    assert warnings == []


async def test_audit_strips_refs_never_seen() -> None:
    findings = GapFindings(
        findings=[GapFinding(doc_kind="birth_certificate", rationale="x", refs=["ghost"])]
    )
    kept, warnings = await chase._audit_gaps(
        findings, seen_refs=["real"], present_types=set(), required_types=set()
    )
    assert kept == []
    assert any("never seen" in w for w in warnings)


async def test_audit_keeps_finding_backed_by_seen_ref() -> None:
    findings = GapFindings(
        findings=[GapFinding(doc_kind="i864", rationale="dependent found", refs=["real", "ghost"])]
    )
    kept, _ = await chase._audit_gaps(
        findings, seen_refs=["real"], present_types=set(), required_types=set()
    )
    assert len(kept) == 1 and kept[0].refs == ["real"]  # ghost stripped, finding survives


async def test_audit_drops_uncited_gap_not_in_registry() -> None:
    findings = GapFindings(findings=[GapFinding(doc_kind="random_doc", rationale="x", refs=[])])
    kept, warnings = await chase._audit_gaps(
        findings, seen_refs=[], present_types=set(), required_types={"passport"}
    )
    assert kept == []
    assert any("not a code-verified absence" in w for w in warnings)


# --- Grant-block regression (MANDATORY) ------------------------------------
async def test_chase_grants_block_non_granted_tools() -> None:
    """The chase agent's registry grants only firm-data reads; a model call to a
    deepagents builtin (write_file) or a web tool (fetch_page) is refused at the
    execution layer — zero dispatches."""
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
        emit=lambda _e: None, node="reason_gaps",
    )
    await run_tool_loop(
        model=scripted(*turns), task_prompt="p",
        tools=loop.granted_registry(chase._GRANTS),
        budget=AgentBudget(max_tool_calls=5), ctx=ctx,
    )
    assert transcript.tool_calls == 0


# --- Full graph interrupt/resume -------------------------------------------
@pytest.fixture
def graph_seams(tmp_path: Path, monkeypatch):
    """Wire chase to a tmp store + fake doc store + scripted model + faked
    distillation. The scripted model calls list_matter_docs (recording the
    matter's real doc_ids into seen_refs); the faked distill returns a mixed
    gap set (one legit absence, one fabricated 'missing' for a present doc)."""
    store = make_store(tmp_path)
    doc_store = FakeDocStore()
    monkeypatch.setattr(chase, "get_matter_store", lambda: store)
    monkeypatch.setattr(chase, "get_store", lambda: doc_store)
    monkeypatch.setattr(chase, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(loop, "make_client", lambda s: None)

    async def fake_call_gemini(client, model, prompt, wrapper, settings, **kwargs):
        if wrapper is GapFindings:
            return GapFindings(
                findings=[
                    GapFinding(doc_kind="g28", rationale="required, absent", refs=[]),
                    GapFinding(doc_kind="passport", rationale="claims missing", refs=[]),
                ]
            )
        if wrapper is ChaseDraft:
            return ChaseDraft(subject="Document request", body="Please send the G-28.")
        raise AssertionError(f"unexpected wrapper {wrapper}")

    monkeypatch.setattr(loop, "call_gemini", fake_call_gemini)
    return store, doc_store


async def test_chase_full_arc_records_memory_and_audits(graph_seams, monkeypatch) -> None:
    store, doc_store = graph_seams
    scope, _ = await bootstrap(store)
    matter = await store.create_matter(scope, "immigration", "Petition")
    passport = await store.add_document(scope, matter.id, "a" * 64, "passport", "p.pdf")
    doc_store.put(passport.doc_id, "passport", "final", detected="passport")

    turns = [
        tool_call_msg(("list_matter_docs", {"matter_id": matter.id})),
        AIMessage(content="Investigation complete."),
    ]
    monkeypatch.setattr(loop, "make_agent_model", lambda settings, live=False: scripted(*turns))

    graph = chase.build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "chase-1"}}
    state = ChaseState(
        run_id="run-1", firm_id=scope.firm_id, user_id=scope.user_id,
        matter_id=matter.id, case_type="g28_filing",
    )
    result = await graph.ainvoke(state, config=config)

    # Parked at review: the legit g28 gap survived, the fabricated passport
    # gap was dropped with a warning.
    interrupts = result["__interrupt__"]
    payload = interrupts[0].value
    assert [g["doc_kind"] for g in payload["gaps"]] == ["g28"]
    assert any("passport" in w for w in payload["warnings"])
    assert len(payload["drafts"]) == 1  # one draft for the surviving gap

    # Resume approving the audited set unchanged → finalize.
    final = await graph.ainvoke(Command(resume={"gaps": None}), config=config)
    report = final["report"]
    assert [g["doc_kind"] for g in report["gaps"]] == ["g28"]

    # finalize recorded the approved gaps to firm memory.
    memories = await store.list_memories(scope, matter_type="g28_filing")
    assert len(memories) == 1
    assert memories[0].kind == "outcome_note"
    assert "g28" in memories[0].summary
