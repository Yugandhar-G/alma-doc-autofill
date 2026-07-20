"""Packet Pre-Flight v0 — unit tests per check, graph interrupt/resume flow,
and the API surface (with the extract seam patched, no LLM/network)."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

import app.main as m
import app.packages.preflight.api as api
from app.packages.preflight.checks import (
    check_ids,
    evidence_completeness,
    form_edition_currency,
    i864_sufficiency,
    identity_consistency,
    income_sufficient,
    run_checks,
)
from app.packages.preflight.graph import build_graph
from app.packages.preflight.knowledge import form_editions
from app.packages.preflight.knowledge.poverty_guidelines import threshold
from app.packages.preflight.packet import gather_packet
from app.packages.preflight.state import PreflightState
from app.schemas import BeneficiaryInfo, ExtractionEnvelope, G28Data, PassportData


# --- fixtures / builders --------------------------------------------------- #


def _passport(source_hash="a" * 64, **fields) -> ExtractionEnvelope:
    return ExtractionEnvelope(
        document_type_requested="passport",
        document_type_detected="passport",
        data=PassportData(**fields).model_dump(),
        source_hash=source_hash,
    )


def _g28(source_hash="b" * 64, family_name=None, given_name=None) -> ExtractionEnvelope:
    return ExtractionEnvelope(
        document_type_requested="g28",
        document_type_detected="g28",
        data=G28Data(
            beneficiary=BeneficiaryInfo(family_name=family_name, given_name=given_name)
        ).model_dump(),
        source_hash=source_hash,
    )


def _packet(envelopes, case_type="g28_filing", declared_editions=None):
    return gather_packet(list(envelopes), case_type, declared_editions)


SYNTHETIC_REG = {
    "g-28": form_editions.FormEdition("g-28", "05/31/24", "https://example.test/g-28")
}


# --- identity_consistency -------------------------------------------------- #


def test_identity_clean_packet_zero_findings():
    packet = _packet(
        [_passport(surname="GARCIA", given_names="MARIA"), _g28(family_name="Garcia", given_name="Maria")]
    )
    assert identity_consistency(packet) == []
    assert run_checks(packet) == []  # the fabrication-bait contract


def test_identity_surname_mismatch_cites_both_docs():
    packet = _packet(
        [
            _passport("c" * 64, surname="GARCIA", given_names="MARIA"),
            _g28("d" * 64, family_name="SMITH", given_name="Maria"),
        ]
    )
    findings = identity_consistency(packet)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "identity_consistency"
    assert finding.severity == "critical"
    refs = {(r.kind, r.ref, r.excerpt) for r in finding.refs}
    assert ("doc", "c" * 64, "GARCIA") in refs
    assert ("doc", "d" * 64, "SMITH") in refs


def test_identity_diacritics_and_case_fold_to_no_finding():
    packet = _packet(
        [_passport(surname="JOSÉ", given_names="M"), _g28(family_name="jose", given_name="m")]
    )
    assert identity_consistency(packet) == []


def test_identity_null_on_one_side_is_skipped():
    # G-28 beneficiary given_name null → given_names not compared, no finding.
    packet = _packet(
        [_passport(surname="LEE", given_names="SAM"), _g28(family_name="Lee", given_name=None)]
    )
    assert identity_consistency(packet) == []


def test_identity_passport_number_mismatch_across_two_passports():
    packet = _packet(
        [
            _passport("1" * 64, surname="ROSSI", passport_number="AA1111111"),
            _passport("2" * 64, surname="ROSSI", passport_number="ZZ9999999"),
        ]
    )
    findings = identity_consistency(packet)
    assert len(findings) == 1
    assert "passport number" in findings[0].message


# --- evidence_completeness ------------------------------------------------- #


def test_completeness_missing_g28_is_critical_with_no_refs():
    packet = _packet([_passport(surname="NGUYEN")])
    findings = evidence_completeness(packet)
    assert len(findings) == 1
    assert findings[0].check_id == "evidence_completeness"
    assert findings[0].severity == "critical"
    assert findings[0].refs == []  # absence findings honestly carry no refs


def test_completeness_all_present_is_silent():
    packet = _packet([_passport(surname="A"), _g28(family_name="A")])
    assert evidence_completeness(packet) == []


def test_completeness_unknown_case_type_is_silent():
    packet = _packet([_passport(surname="A")], case_type="unknown_case")
    assert evidence_completeness(packet) == []


# --- form_edition_currency ------------------------------------------------- #


def test_edition_dormant_without_registry_entry():
    # Declared edition present but NO registry entry for the form → silence.
    # (The production registry now derives from the verified forms plane, so
    # dormancy is proven by emptying the derived map, not by case accidents.)
    packet = _packet([_g28(family_name="A")], declared_editions={"g-28": "03/01/20"})
    with patch.object(form_editions, "_derived_registry", lambda: {}):
        assert form_edition_currency(packet) == []


def test_edition_dormant_without_declared_edition():
    # Registry has an entry but v0 extraction declares no edition → silence.
    packet = _packet([_g28(family_name="A")])
    with patch.object(form_editions, "_REGISTRY", SYNTHETIC_REG):
        assert form_edition_currency(packet) == []


def test_edition_stale_fires_warning_with_synthetic_registry():
    packet = _packet([_g28(family_name="A")], declared_editions={"g-28": "03/01/20"})
    with patch.object(form_editions, "_REGISTRY", SYNTHETIC_REG):
        findings = form_edition_currency(packet)
    assert len(findings) == 1
    assert findings[0].check_id == "form_edition_currency"
    assert findings[0].severity == "warning"
    assert findings[0].refs[0].ref == "https://example.test/g-28"


def test_edition_current_is_silent():
    packet = _packet([_g28(family_name="A")], declared_editions={"g-28": "05/31/24"})
    with patch.object(form_editions, "_REGISTRY", SYNTHETIC_REG):
        assert form_edition_currency(packet) == []


# --- i864_sufficiency + income math ---------------------------------------- #


def test_i864_check_is_structure_only():
    packet = _packet([_passport(surname="A"), _g28(family_name="A")])
    assert i864_sufficiency(packet) == []


def test_income_thresholds_match_transcribed_table():
    # Verbatim from docs/immigration-ai-market-research.md §3.1 (125% column).
    assert threshold(2026, 2, "p125") == 24_650
    assert threshold(2026, 4, "p125") == 37_500
    assert threshold(2026, 8, "p125") == 63_200
    assert threshold(2026, 2, "p100") == 19_720


def test_income_sufficient_boundary():
    assert income_sufficient(37_500, 4, 2026) is True
    assert income_sufficient(37_499, 4, 2026) is False


def test_income_household_above_table_uses_increment():
    # Household of 9 = size-8 row + one "each additional" (+$7,100 at 125%).
    assert threshold(2026, 9, "p125") == 63_200 + 7_100


def test_income_math_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        threshold(2099, 4, "p125")  # untabulated year
    with pytest.raises(ValueError):
        threshold(2026, 1, "p125")  # below table floor
    with pytest.raises(ValueError):
        threshold(2026, 4, "p150")  # unknown band


# --- checks_run audit trail ------------------------------------------------ #


def test_check_ids_lists_the_whole_battery():
    assert check_ids() == [
        "identity_consistency",
        "evidence_completeness",
        "form_edition_currency",
        "i864_sufficiency",
    ]


# --- graph interrupt / resume flow ----------------------------------------- #


async def test_graph_parks_at_review_then_finalizes():
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "pf-1"}}
    first = await graph.ainvoke(
        PreflightState(
            run_id="pf-1",
            envelopes=[_passport(surname="GARCIA"), _g28(family_name="SMITH", given_name="M")],
        ),
        config=config,
    )
    assert "__interrupt__" in first
    draft = first["__interrupt__"][0].value["report"]
    assert draft["ok"] is False
    assert len(draft["findings"]) == 1
    assert draft["checks_run"] == check_ids()
    assert draft["docs_examined"] == 2

    # Approve the draft unchanged (findings=None).
    final = await graph.ainvoke(Command(resume={"findings": None}), config=config)
    report = final["report"]
    assert len(report.findings) == 1 and report.ok is False


async def test_graph_reviewer_can_clear_findings():
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "pf-2"}}
    await graph.ainvoke(
        PreflightState(
            run_id="pf-2",
            envelopes=[_passport(surname="GARCIA"), _g28(family_name="SMITH", given_name="M")],
        ),
        config=config,
    )
    final = await graph.ainvoke(Command(resume={"findings": []}), config=config)
    report = final["report"]
    assert report.findings == [] and report.ok is True  # criticals cleared → ok


async def test_graph_clean_packet_finalizes_ok_zero_findings():
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "pf-clean"}}
    first = await graph.ainvoke(
        PreflightState(
            run_id="pf-clean",
            envelopes=[_passport(surname="GARCIA", given_names="MARIA"), _g28(family_name="Garcia", given_name="Maria")],
        ),
        config=config,
    )
    assert first["__interrupt__"][0].value["report"]["findings"] == []
    final = await graph.ainvoke(Command(resume={"findings": None}), config=config)
    assert final["report"].ok is True and final["report"].findings == []


async def test_graph_review_rejects_invalid_edit():
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "pf-bad"}}
    await graph.ainvoke(
        PreflightState(run_id="pf-bad", envelopes=[_passport(surname="GARCIA")]),
        config=config,
    )
    with pytest.raises(Exception):
        await graph.ainvoke(
            Command(resume={"findings": [{"severity": "not-a-severity"}]}),
            config=config,
        )


# --- API surface (extract seam patched) ------------------------------------ #


@pytest.fixture
def client(monkeypatch):
    # Fresh RunManager + MemorySaver so API tests don't touch disk or leak the
    # compiled graph across the session.
    from app.kernel.runtime import RunManager

    monkeypatch.setattr(api, "_RUNS", RunManager())

    async def _mem_graph():
        return build_graph(checkpointer=MemorySaver())

    monkeypatch.setattr(api, "_build_preflight_graph", _mem_graph)
    return TestClient(m.app)


def _fake_slots(passport_surname="GARCIA", g28_family="SMITH"):
    async def _extract(passport_front, passport_back, g28):
        return {
            "passport": _passport("a" * 64, surname=passport_surname, given_names="MARIA").model_dump(),
            "g28": _g28("b" * 64, family_name=g28_family, given_name="MARIA").model_dump(),
        }

    return _extract


def test_api_run_parks_at_review_with_draft_report(client):
    with patch.object(api, "extract_slots", side_effect=_fake_slots(g28_family="SMITH")):
        resp = client.post(
            "/api/packages/preflight/runs",
            files={"passport_front": ("p.png", b"x", "image/png"), "g28": ("g.png", b"y", "image/png")},
        )
    body = resp.json()
    assert body["success"] is True
    run_id = body["data"]["run_id"]
    report = body["data"]["report"]
    assert report["ok"] is False
    assert any(f["check_id"] == "identity_consistency" for f in report["findings"])

    # Status peek shows awaiting_review.
    status = client.get(f"/api/packages/preflight/runs/{run_id}").json()
    assert status["data"]["status"] == "awaiting_review"

    # Resume approving the draft → final report echoes the critical finding.
    resumed = client.post(f"/api/packages/preflight/runs/{run_id}/resume", json={}).json()
    assert resumed["success"] is True
    assert resumed["data"]["ok"] is False
    assert resumed["data"]["case_type"] == "g28_filing"


def test_api_clean_packet_reports_ok(client):
    with patch.object(api, "extract_slots", side_effect=_fake_slots(g28_family="Garcia")):
        resp = client.post(
            "/api/packages/preflight/runs",
            files={"passport_front": ("p.png", b"x", "image/png"), "g28": ("g.png", b"y", "image/png")},
        )
    report = resp.json()["data"]["report"]
    assert report["findings"] == [] and report["ok"] is True


def test_api_no_files_rejected(client):
    resp = client.post("/api/packages/preflight/runs")
    assert resp.json()["success"] is False


def test_api_resume_unknown_run_is_error(client):
    resp = client.post("/api/packages/preflight/runs/nope/resume", json={})
    assert resp.json()["success"] is False


def test_api_status_unknown_run_is_error(client):
    resp = client.get("/api/packages/preflight/runs/nope")
    assert resp.json()["success"] is False
