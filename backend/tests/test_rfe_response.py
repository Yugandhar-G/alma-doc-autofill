"""RFE-response assembler — pure deadline/audit/cover units, the full graph
interrupt/resume arc on MemorySaver (extraction + distillation seams patched,
no LLM/network/key), memory-write with/without matter context, and the API
surface (seams patched)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

import app.packages.rfe_response.api as api
import app.packages.rfe_response.graph as graph_mod
from app.kernel.config import Settings, get_settings
from app.kernel.store.base import get_matter_store
from app.kernel.store.sqlite_store import SqliteMatterStore
from app.main import create_app
from app.packages.rfe_response.deadlines import deadline_status, is_critical
from app.packages.rfe_response.graph import build_graph
from app.packages.rfe_response.package import PACKAGE as RFE_PACKAGE
from app.packages.rfe_response.refs_audit import (
    audit_checklist,
    build_cover_structure,
)
from app.packages.rfe_response.schemas import (
    ChecklistItem,
    ResponseChecklist,
    RfeGround,
    RfeNotice,
    RfeResponseState,
)
from tests.matter_intake_util import bootstrap


# --- builders --------------------------------------------------------------
def _ground(gid="g1", text="Sustained acclaim not established.", req="Awards evidence.") -> RfeGround:
    return RfeGround(ground_id=gid, quoted_text=text, requested_evidence=req)


def _notice(grounds=None, deadline="2026-03-15", form_id="I-129") -> RfeNotice:
    return RfeNotice(
        receipt_number="EAC0000000000",
        form_id=form_id,
        notice_date="2025-12-01",
        response_deadline=deadline,
        grounds=grounds if grounds is not None else [_ground("g1"), _ground("g2", "Role not critical.")],
    )


# --- deadline math (pure) --------------------------------------------------
def test_deadline_comfortable_future_has_no_warning():
    days, warning = deadline_status("2026-03-15", "2026-01-01")
    assert days == 73 and warning is None


def test_deadline_warning_band_boundaries():
    # 30 days out → no warning (>= WARNING_DAYS); 29 → warning.
    assert deadline_status("2026-01-31", "2026-01-01")[1] is None      # 30 days
    assert "Warning" in deadline_status("2026-01-30", "2026-01-01")[1]  # 29 days


def test_deadline_critical_band_boundaries():
    # 14 days → warning (not critical); 13 → critical.
    assert "Warning" in deadline_status("2026-01-15", "2026-01-01")[1]   # 14 days
    assert "Critical" in deadline_status("2026-01-14", "2026-01-01")[1]  # 13 days


def test_deadline_past_is_negative_and_critical():
    days, warning = deadline_status("2025-12-15", "2026-01-01")
    assert days == -17 and "passed" in warning
    assert is_critical(days) is True


def test_deadline_null_is_unverifiable_never_guessed():
    days, warning = deadline_status(None, "2026-01-01")
    assert days is None and "unverifiable" in warning
    assert is_critical(None) is True


def test_deadline_unparseable_is_unverifiable():
    days, warning = deadline_status("not-a-date", "2026-01-01")
    assert days is None and "unverifiable" in warning


def test_deadline_leap_day_arithmetic():
    # 2024 is a leap year: Feb 29 exists → one calendar day to Mar 1.
    assert deadline_status("2024-03-01", "2024-02-29")[0] == 1
    # Across the leap day from Feb 28 → Mar 1 is two days in a leap year.
    assert deadline_status("2024-03-01", "2024-02-28")[0] == 2


# --- checklist audit (pure) ------------------------------------------------
def test_audit_drops_item_for_fabricated_ground():
    items = [ChecklistItem(ground_id="g99", action="x", refs=["g99"])]
    kept, warnings = audit_checklist(items, ground_ids=["g1"], matter_doc_ids=[])
    assert kept == []
    assert any("fabricated ground" in w for w in warnings)


def test_audit_strips_invented_ref_but_keeps_item():
    items = [ChecklistItem(ground_id="g1", action="x", refs=["g1", "ghost"])]
    kept, warnings = audit_checklist(items, ground_ids=["g1"], matter_doc_ids=[])
    assert len(kept) == 1 and kept[0].refs == ["g1"]
    assert any("invented ref" in w for w in warnings)


def test_audit_allows_matter_doc_id_as_ref():
    doc = "a" * 64
    items = [ChecklistItem(ground_id="g1", action="x", refs=["g1", doc])]
    kept, warnings = audit_checklist(items, ground_ids=["g1"], matter_doc_ids=[doc])
    assert kept[0].refs == ["g1", doc] and warnings == []


def test_cover_structure_one_heading_per_addressed_ground_in_order():
    grounds = [_ground("g1"), _ground("g2", "Role not critical.", "Letters."), _ground("g3", "Third.", "More.")]
    kept = [ChecklistItem(ground_id="g2", action="x"), ChecklistItem(ground_id="g1", action="y")]
    cover = build_cover_structure(grounds, kept)
    # Leading + trailing bookend headings, one middle section per addressed
    # ground in NOTICE order (g1 then g2), g3 omitted (unaddressed).
    assert cover[0].startswith("Cover letter")
    assert cover[-1].startswith("Exhibit index")
    middle = cover[1:-1]
    assert [h.split(":")[0] for h in middle] == ["Response to ground g1", "Response to ground g2"]


# --- graph seams -----------------------------------------------------------
@pytest.fixture
def seams(monkeypatch):
    """Patch the three graph seams: vision extraction, checklist distillation,
    and make_client. get_settings returns a keyless Settings (call_gemini is
    faked, so no key is ever required)."""
    monkeypatch.setattr(graph_mod, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(graph_mod, "make_client", lambda s: None)

    async def fake_extract(file_bytes, filename):
        return _notice()

    async def fake_checklist(client, model, prompt, wrapper, settings, **kwargs):
        assert wrapper is ResponseChecklist
        return ResponseChecklist(
            items=[
                ChecklistItem(ground_id="g1", action="Gather awards", doc_kinds=["award"], refs=["g1"]),
                ChecklistItem(ground_id="g2", action="Obtain letters", doc_kinds=["recommendation_letter"], refs=["g2"]),
            ]
        )

    monkeypatch.setattr(graph_mod, "extract_notice_document", fake_extract)
    monkeypatch.setattr(graph_mod, "call_gemini", fake_checklist)
    return fake_extract, fake_checklist


def _state(**kw) -> RfeResponseState:
    base = dict(run_id="r1", today="2026-01-01", notice_bytes=b"x", notice_filename="rfe.pdf")
    base.update(kw)
    return RfeResponseState(**base)


async def test_graph_full_arc_parks_then_finalizes_ok(seams):
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "rfe-1"}}
    first = await graph.ainvoke(_state(), config=config)

    assert "__interrupt__" in first
    payload = first["__interrupt__"][0].value
    report = payload["report"]
    assert report["notice"]["response_deadline"] == "2026-03-15"
    assert [i["ground_id"] for i in report["checklist"]["items"]] == ["g1", "g2"]
    assert report["deadline_days_remaining"] == 73
    assert report["ok"] is True  # verifiable, >14 days, all grounds covered
    # Cover structure is code-assembled (not from the model).
    assert report["checklist"]["cover_structure"][0].startswith("Cover letter")

    final = await graph.ainvoke(Command(resume={"checklist": None}), config=config)
    assert final["report"].ok is True
    assert len(final["report"].checklist.items) == 2


async def test_graph_extract_clears_notice_bytes(seams):
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "rfe-bytes"}}
    await graph.ainvoke(_state(), config=config)
    snapshot = await graph.aget_state(config)
    assert snapshot.values["notice_bytes"] is None  # cleared post-extraction


async def test_graph_drops_fabricated_ground_in_checklist(monkeypatch, seams):
    async def fab_checklist(client, model, prompt, wrapper, settings, **kwargs):
        return ResponseChecklist(
            items=[
                ChecklistItem(ground_id="g1", action="ok", refs=["g1"]),
                ChecklistItem(ground_id="g2", action="ok", refs=["g2"]),
                ChecklistItem(ground_id="g99", action="fabricated ground item", refs=["g99"]),
            ]
        )

    monkeypatch.setattr(graph_mod, "call_gemini", fab_checklist)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "rfe-fab"}}
    first = await graph.ainvoke(_state(), config=config)
    payload = first["__interrupt__"][0].value
    assert [i["ground_id"] for i in payload["report"]["checklist"]["items"]] == ["g1", "g2"]
    assert any("fabricated ground" in w for w in payload["warnings"])


async def test_graph_null_deadline_warns_and_not_ok(monkeypatch, seams):
    async def null_deadline_notice(file_bytes, filename):
        return _notice(grounds=[_ground("g1")], deadline=None)

    monkeypatch.setattr(graph_mod, "extract_notice_document", null_deadline_notice)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "rfe-null"}}
    first = await graph.ainvoke(_state(), config=config)
    report = first["__interrupt__"][0].value["report"]
    assert report["deadline_days_remaining"] is None
    assert "unverifiable" in report["deadline_warning"]
    assert report["ok"] is False


async def test_graph_parse_grounds_drops_empty_and_reassigns_ids(monkeypatch, seams):
    async def messy_notice(file_bytes, filename):
        return _notice(
            grounds=[
                RfeGround(ground_id="x", quoted_text="", requested_evidence="empty → dropped"),
                RfeGround(ground_id="zzz", quoted_text="Real ground.", requested_evidence="evidence"),
            ]
        )

    monkeypatch.setattr(graph_mod, "extract_notice_document", messy_notice)

    async def one_item(client, model, prompt, wrapper, settings, **kwargs):
        return ResponseChecklist(items=[ChecklistItem(ground_id="g1", action="ok", refs=["g1"])])

    monkeypatch.setattr(graph_mod, "call_gemini", one_item)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "rfe-messy"}}
    first = await graph.ainvoke(_state(), config=config)
    grounds = first["__interrupt__"][0].value["report"]["notice"]["grounds"]
    assert [g["ground_id"] for g in grounds] == ["g1"]  # empty dropped, id reassigned
    assert grounds[0]["quoted_text"] == "Real ground."


async def test_graph_resume_with_edited_checklist_revalidates(seams):
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "rfe-edit"}}
    await graph.ainvoke(_state(), config=config)
    edited = {"items": [{"ground_id": "g1", "action": "edited action", "doc_kinds": [], "refs": ["g1"]}], "cover_structure": []}
    final = await graph.ainvoke(Command(resume={"checklist": edited}), config=config)
    items = final["report"].checklist.items
    assert len(items) == 1 and items[0].action == "edited action"
    # Cover re-derived in code from the edited items (g2 no longer addressed).
    cover = final["report"].checklist.cover_structure
    assert [h for h in cover if h.startswith("Response to ground")] == ["Response to ground g1: Awards evidence."]


# --- memory write (matter context) ----------------------------------------
async def test_finalize_records_rfe_memory_with_matter(tmp_path: Path, monkeypatch, seams):
    store = SqliteMatterStore(Settings(_env_file=None, matter_store_path=str(tmp_path / "m.db")))
    scope, _ = await bootstrap(store)
    matter = await store.create_matter(scope, "immigration", "Petition")
    doc = await store.add_document(scope, matter.id, "a" * 64, "passport", "p.pdf")
    monkeypatch.setattr(graph_mod, "get_matter_store", lambda: store)

    # Checklist may cite the matter doc; the audit keeps it as a valid ref.
    async def checklist_with_doc(client, model, prompt, wrapper, settings, **kwargs):
        return ResponseChecklist(
            items=[
                ChecklistItem(ground_id="g1", action="use passport", refs=["g1", doc.doc_id]),
                ChecklistItem(ground_id="g2", action="letters", refs=["g2"]),
            ]
        )

    monkeypatch.setattr(graph_mod, "call_gemini", checklist_with_doc)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "rfe-mem"}}
    await graph.ainvoke(
        _state(firm_id=scope.firm_id, user_id=scope.user_id, matter_id=matter.id),
        config=config,
    )
    final = await graph.ainvoke(Command(resume={"checklist": None}), config=config)
    kept = {i.ground_id: i for i in final["report"].checklist.items}
    assert doc.doc_id in kept["g1"].refs  # matter doc survived as a valid ref

    memories = await store.list_memories(scope, matter_type="immigration")
    assert len(memories) == 1
    assert memories[0].kind == "rfe"
    assert memories[0].criterion_key == "I-129"
    assert "2 ground(s)" in memories[0].summary


async def test_finalize_skips_memory_without_matter(tmp_path: Path, monkeypatch, seams):
    store = SqliteMatterStore(Settings(_env_file=None, matter_store_path=str(tmp_path / "m.db")))
    scope, _ = await bootstrap(store)
    monkeypatch.setattr(graph_mod, "get_matter_store", lambda: store)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "rfe-nomem"}}
    await graph.ainvoke(_state(), config=config)  # no matter/firm ids
    await graph.ainvoke(Command(resume={"checklist": None}), config=config)
    assert await store.list_memories(scope, matter_type="immigration") == []


# --- API surface -----------------------------------------------------------
@pytest.fixture
def client(tmp_path: Path, monkeypatch, seams):
    settings = Settings(
        _env_file=None,
        matter_store_path=str(tmp_path / "matters.db"),
        local_storage_dir=str(tmp_path / "blobs"),
    )
    store = SqliteMatterStore(settings)
    monkeypatch.setattr(graph_mod, "get_matter_store", lambda: store)

    from app.kernel.runtime import RunManager

    monkeypatch.setattr(api, "_RUNS", RunManager())

    async def _mem_graph():
        return build_graph(checkpointer=MemorySaver())

    monkeypatch.setattr(api, "_build_rfe_graph", _mem_graph)

    app = create_app(registry=(RFE_PACKAGE,))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_matter_store] = lambda: store
    with TestClient(app) as c:
        yield c, store


def test_api_run_parks_at_review_then_resume(client):
    c, _ = client
    resp = c.post(
        "/api/packages/rfe_response/runs",
        files={"notice": ("rfe.png", b"x", "image/png")},
    )
    body = resp.json()
    assert body["success"] is True, body
    run_id = body["data"]["run_id"]
    report = body["data"]["report"]
    assert [i["ground_id"] for i in report["checklist"]["items"]] == ["g1", "g2"]

    status = c.get(f"/api/packages/rfe_response/runs/{run_id}").json()
    assert status["data"]["status"] == "awaiting_review"

    resumed = c.post(f"/api/packages/rfe_response/runs/{run_id}/resume", json={}).json()
    # ok reflects the real-clock deadline check (today is stamped by the API),
    # so assert the run finalized with the audited checklist rather than a
    # clock-dependent ok value.
    assert resumed["success"] is True
    assert [i["ground_id"] for i in resumed["data"]["checklist"]["items"]] == ["g1", "g2"]


def test_api_no_notice_rejected(client):
    c, _ = client
    assert c.post("/api/packages/rfe_response/runs").json()["success"] is False


def test_api_unknown_matter_rejected(client):
    c, _ = client
    resp = c.post(
        "/api/packages/rfe_response/runs",
        files={"notice": ("rfe.png", b"x", "image/png")},
        data={"matter_id": "does-not-exist"},
    )
    assert resp.json()["success"] is False


def test_api_resume_unknown_run_is_error(client):
    c, _ = client
    assert c.post("/api/packages/rfe_response/runs/nope/resume", json={}).json()["success"] is False


def test_api_status_unknown_run_is_error(client):
    c, _ = client
    assert c.get("/api/packages/rfe_response/runs/nope").json()["success"] is False
