"""B1 demo gates: the package registry surfaces both workflows, and an
autofill run parked at review survives a process restart (new graph instance
over the same SQLite checkpoint file resumes it to a report)."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langgraph.types import Command

import app.main as m
import app.packages.autofill.graph as autofill_graph
from app.packages.autofill.state import AutofillState
from app.schemas import ExtractionEnvelope, PassportData, PopulationReport


def _envelope() -> ExtractionEnvelope:
    return ExtractionEnvelope(
        document_type_requested="passport",
        document_type_detected="passport",
        data=PassportData(surname="GARCIA", given_names="MARIA").model_dump(),
        source_hash="a" * 64,
        model_used="test",
    )


def test_packages_catalog_lists_both_manifests():
    client = TestClient(m.app)
    resp = client.get("/api/packages")
    body = resp.json()
    assert body["success"] is True
    ids = {p["package_id"] for p in body["data"]["packages"]}
    assert ids == {"autofill", "screener"}
    autofill = next(p for p in body["data"]["packages"] if p["package_id"] == "autofill")
    assert autofill["interrupt_kinds"] == ["extraction_review"]
    assert [s["id"] for s in autofill["stages"]] == ["review", "populate"]


async def _open_graph(path):
    from app.kernel.runtime import open_sqlite_checkpointer

    return autofill_graph.build_graph(checkpointer=await open_sqlite_checkpointer(path))


async def test_autofill_run_survives_restart_mid_review(tmp_path):
    """Start a run → parks at review_gate → 'restart' (brand-new graph over
    the same checkpoint file) → resume with reviewed data → report."""
    db = tmp_path / "checkpoints.db"
    config = {"configurable": {"thread_id": "run-restart-test"}}

    graph_before = await _open_graph(db)
    first = await graph_before.ainvoke(
        AutofillState(run_id="run-restart-test", passport_envelope=_envelope()),
        config=config,
    )
    assert "__interrupt__" in first, "run must park at review"
    payload = first["__interrupt__"][0].value
    assert payload["passport"]["data"]["surname"] == "GARCIA"

    # --- simulated restart: a completely new compiled graph + connection ---
    graph_after = await _open_graph(db)
    snapshot = await graph_after.aget_state(config)
    assert snapshot.next, "interrupt must survive the restart"

    fake_report = PopulationReport(
        target_url="offline", filled=1, skipped_null=0, mismatches=0, errors=0, ok=True
    )

    async def fake_populate(passport, g28, headed=None):
        assert passport is not None and passport.surname == "GARCIA"
        return fake_report

    with patch.object(autofill_graph, "populate_form", side_effect=fake_populate):
        result = await graph_after.ainvoke(
            Command(
                resume={
                    "passport": PassportData(surname="GARCIA").model_dump(),
                    "g28": None,
                    "headed": None,
                }
            ),
            config=config,
        )
    report = result.get("report")
    assert report is not None and report.ok


async def test_autofill_review_rejects_invalid_edit(tmp_path):
    """An edited value re-validates through the same schema — junk shapes
    fail loudly instead of flowing to populate."""
    from langgraph.checkpoint.memory import MemorySaver

    graph = autofill_graph.build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "run-invalid-edit"}}
    await graph.ainvoke(
        AutofillState(run_id="run-invalid-edit", passport_envelope=_envelope()),
        config=config,
    )
    with pytest.raises(Exception):
        await graph.ainvoke(
            Command(resume={"passport": {"surname": 123.45, "sex": "INVALID"}}),
            config=config,
        )
