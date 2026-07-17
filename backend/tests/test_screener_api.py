"""Screener API seam tests — graph and evidence extraction faked at the api
module boundary, mirroring test_api.py's approach. SSE framing is parsed for
the streaming endpoints."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import EvidenceDocRecord, ScreenerReport, VisaVerdict
from app.screener import api as screener_api


def _events(response) -> list[dict]:
    """Parse SSE body into event dicts."""
    events = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


class FakeGraph:
    """Pauses at review on first run; completes on resume."""

    def __init__(self):
        self.states: dict[str, dict] = {}

    async def astream(self, input_obj, config=None, stream_mode=None):
        thread = config["configurable"]["thread_id"]
        from langgraph.types import Command

        if isinstance(input_obj, Command):
            state = self.states[thread]
            yield ("custom", {"type": "model_thinking", "node": "assess_one", "text": "weighing the award"})
            yield ("updates", {"assess_one": {}})
            report = ScreenerReport(
                session_id=thread,
                visa_targets=state["visa_targets"],
                verdicts=[
                    VisaVerdict(visa=v, recommendation="possible", confidence="medium")
                    for v in state["visa_targets"]
                ],
            )
            state["report"] = report
            state["awaiting"] = False
            yield ("updates", {"assemble_report": {}})
        else:
            self.states[thread] = {
                "visa_targets": list(input_obj.visa_targets),
                "report": None,
                "awaiting": True,
            }
            yield ("custom", {"type": "evidence_scan", "node": "compile_matrix", "facts": ["Best Paper"]})
            yield ("updates", {"compile_matrix": {}})
            yield (
                "updates",
                {"__interrupt__": (type("I", (), {"value": {"matrix": {"items": [], "unmapped_docs": []}}})(),)},
            )

    async def aget_state(self, config):
        thread = config["configurable"]["thread_id"]
        state = self.states.get(thread)

        class Snapshot:
            values = {"report": state["report"]} if state else {}
            next = ("review_gate",) if state and state.get("awaiting") else ()

        return Snapshot() if state else type("S", (), {"values": {}, "next": ()})()


@pytest.fixture
def client(monkeypatch):
    screener_api._SESSIONS.clear()
    fake = FakeGraph()

    async def fake_get_graph():
        return fake

    monkeypatch.setattr(screener_api, "_get_graph", fake_get_graph)
    return TestClient(app)


def _make_session(client) -> str:
    body = client.post("/api/screener/session").json()
    assert body["success"] is True
    return body["data"]["session_id"]


INTAKE_BODY = {
    "visa_targets": ["O1A"],
    "intake": {"field_of_endeavor": "Robotics", "awards": ["RSS Best Paper"]},
}


def test_full_flow_run_pauses_then_review_completes(client):
    session_id = _make_session(client)
    assert client.put(
        f"/api/screener/session/{session_id}/intake", json=INTAKE_BODY
    ).json()["success"]

    run = client.post(f"/api/screener/session/{session_id}/run")
    assert run.headers["content-type"].startswith("text/event-stream")
    events = _events(run)
    kinds = [e["event"] for e in events]
    assert kinds[0] == "run_started"
    assert "awaiting_review" in kinds
    # The genuine activity feed rides the same stream.
    activity = next(e for e in events if e["event"] == "activity")
    assert activity["type"] == "evidence_scan"
    assert activity["facts"] == ["Best Paper"]

    review = client.post(
        f"/api/screener/session/{session_id}/review",
        json={"matrix": {"items": [], "unmapped_docs": []}},
    )
    events = _events(review)
    kinds = [e["event"] for e in events]
    assert "done" in kinds
    done = next(e for e in events if e["event"] == "done")
    assert done["report"]["disclaimer"]
    thinking = next(e for e in events if e["event"] == "activity")
    assert thinking["type"] == "model_thinking"

    report = client.get(f"/api/screener/session/{session_id}/report").json()
    assert report["success"] is True
    assert report["data"]["session_id"] == session_id


def test_run_requires_intake_first(client):
    session_id = _make_session(client)
    body = client.post(f"/api/screener/session/{session_id}/run").json()
    assert body["success"] is False
    assert "intake" in body["error"].lower()


def test_review_without_run_is_rejected(client):
    session_id = _make_session(client)
    body = client.post(
        f"/api/screener/session/{session_id}/review",
        json={"matrix": {"items": [], "unmapped_docs": []}},
    ).json()
    assert body["success"] is False


def test_unknown_session_rejected(client):
    for method, url, kwargs in (
        ("put", "/api/screener/session/nope/intake", {"json": INTAKE_BODY}),
        ("post", "/api/screener/session/nope/run", {}),
    ):
        body = getattr(client, method)(url, **kwargs).json()
        assert body["success"] is False
        assert "unknown" in body["error"].lower()


def test_intake_rejects_oversized_answers(client):
    session_id = _make_session(client)
    response = client.put(
        f"/api/screener/session/{session_id}/intake",
        json={"intake": {"field_of_endeavor": "x" * 3000}},
    )
    assert response.status_code == 422  # schema cap, fail fast at the boundary


def test_documents_endpoint_isolates_bad_slots(client, monkeypatch):
    session_id = _make_session(client)

    async def fake_extract(content, filename, expected_kind=None):
        if b"bad" in content:
            raise ValueError("Image is too blurry — re-scan and try again.")
        return EvidenceDocRecord(
            source_hash="c" * 64, document_kind_detected="award", key_facts=["Won X"]
        )

    class FakeStore:
        async def save_document(self, content, doc_type, filename):
            return "c" * 64

    monkeypatch.setattr(screener_api, "extract_evidence_document", fake_extract)
    monkeypatch.setattr(screener_api, "get_store", lambda: FakeStore())

    response = client.post(
        f"/api/screener/session/{session_id}/documents",
        files=[
            ("evidence", ("award.png", b"\x89PNG good bytes", "image/png")),
            ("evidence", ("blurry.png", b"\x89PNG bad", "image/png")),
        ],
    )
    body = response.json()
    assert body["success"] is True
    slots = body["data"]["evidence"]
    assert slots[0]["document_kind_detected"] == "award"
    assert "blurry" in slots[1]["error"]
    # The good doc is buffered for the run; the bad one is not.
    assert len(screener_api._SESSIONS[session_id].evidence_docs) == 1


def test_documents_endpoint_caps_count(client, monkeypatch):
    session_id = _make_session(client)
    files = [
        ("evidence", (f"doc{i}.png", b"\x89PNG data", "image/png")) for i in range(9)
    ]
    body = client.post(
        f"/api/screener/session/{session_id}/documents", files=files
    ).json()
    assert body["success"] is False
    assert "at most" in body["error"].lower()
