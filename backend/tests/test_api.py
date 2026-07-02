"""Seam tests for main.py + merge.py: multipart binding, response shapes,
front/back merge, per-slot errors, coherence attachment, final-record audit,
and storage-failure degradation. Extraction and storage are faked — these
tests run offline and keyless."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.schemas import ExtractionEnvelope

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 32
PDF = b"%PDF-1.4 fake"


def envelope(doc_type: str, data: dict | None, detected: str | None = None) -> ExtractionEnvelope:
    return ExtractionEnvelope(
        document_type_requested=doc_type,
        document_type_detected=detected or doc_type,
        data=data,
        warnings=[],
        model_used="test-model",
        source_hash="a" * 64,
    )


def passport_data(**overrides) -> dict:
    fields = [
        "surname", "given_names", "middle_names", "passport_number",
        "country_of_issue", "nationality", "date_of_birth", "place_of_birth",
        "sex", "date_of_issue", "date_of_expiration",
    ]
    return {**{f: None for f in fields}, **overrides}


def g28_data(beneficiary_family="GARCIA", beneficiary_given="MARIA") -> dict:
    attorney = [
        "online_account_number", "family_name", "given_name", "middle_name",
        "street_number_and_name", "apt_ste_flr", "apt_ste_flr_number", "city",
        "state", "zip_code", "country", "daytime_phone", "mobile_phone", "email",
    ]
    eligibility = [
        "is_attorney", "licensing_authority", "bar_number", "subject_to_discipline",
        "law_firm", "is_accredited_representative", "recognized_organization",
        "accreditation_date", "is_associated", "associated_with_name",
        "is_law_student", "law_student_name",
    ]
    return {
        "attorney": {f: None for f in attorney},
        "eligibility": {f: None for f in eligibility},
        "beneficiary": {
            "family_name": beneficiary_family,
            "given_name": beneficiary_given,
            "middle_name": None,
        },
    }


class FakeStore:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.saved: list[tuple[str, ExtractionEnvelope]] = []  # (kind, envelope)

    async def save_document(self, content, doc_type, filename):
        if self.fail:
            raise RuntimeError("storage down")
        return "d" * 64

    async def save_extraction(self, doc_id, envelope, kind="raw"):
        if self.fail:
            raise RuntimeError("storage down")
        self.saved.append((kind, envelope))

    async def get_extraction(self, doc_id, doc_type, kind="raw"):
        return None


@pytest.fixture
def client():
    return TestClient(m.app)


def post_extract(client, store, extract_side_effect, files):
    with patch.object(m, "extract_document", side_effect=extract_side_effect), patch.object(
        m, "get_store", return_value=store
    ):
        return client.post("/api/extract", files=files)


def sequenced(responses: dict[str, list]):
    async def fake(content, filename, doc_type):
        result = responses[doc_type].pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    return fake


def test_happy_path_merge_coherence_and_final_records(client):
    store = FakeStore()
    front = envelope("passport", passport_data(surname="GARCIA"))
    back = envelope("passport", passport_data(given_names="MARIA"))
    g28 = envelope("g28", g28_data("TOTALLYDIFFERENT", "BOB"))
    resp = post_extract(
        client, store, sequenced({"passport": [front, back], "g28": [g28]}),
        files={
            "passport_front": ("f.png", PNG, "image/png"),
            "passport_back": ("b.png", PNG, "image/png"),
            "g28": ("g.pdf", PDF, "application/pdf"),
        },
    )
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    # merge: front authoritative, back fills nulls, back:merge note present
    assert data["passport"]["data"]["surname"] == "GARCIA"
    assert data["passport"]["data"]["given_names"] == "MARIA"
    assert any(w["field"] == "back:merge" for w in data["passport"]["warnings"])
    assert "passport_back" not in data  # back succeeded → no slot error key
    # coherence warnings attached to the g28 envelope in the response
    assert any(w["field"].startswith("beneficiary.") for w in data["g28"]["warnings"])
    # audit: 3 raw records + 2 final records; final g28 carries coherence warnings
    kinds = [kind for kind, _ in store.saved]
    assert kinds.count("raw") == 3 and kinds.count("final") == 2
    final_g28 = next(
        e for kind, e in store.saved
        if kind == "final" and e.document_type_requested == "g28"
    )
    assert any(w.field.startswith("beneficiary.") for w in final_g28.warnings)


def test_oversize_front_is_slot_error_and_back_not_processed(client):
    store = FakeStore()
    big = PNG + b"0" * (11 * 1024 * 1024)
    resp = post_extract(
        client, store, sequenced({"passport": [], "g28": []}),
        files={
            "passport_front": ("f.png", big, "image/png"),
            "passport_back": ("b.png", PNG, "image/png"),
        },
    )
    data = resp.json()["data"]
    assert "exceeds" in data["passport"]["error"]
    assert "front side was rejected" in data["passport_back"]["error"]
    assert store.saved == []


def test_back_without_front_still_extracts_g28(client):
    store = FakeStore()
    g28 = envelope("g28", g28_data())
    resp = post_extract(
        client, store, sequenced({"g28": [g28]}),
        files={
            "passport_back": ("b.png", PNG, "image/png"),
            "g28": ("g.pdf", PDF, "application/pdf"),
        },
    )
    body = resp.json()
    assert body["success"] is True
    assert "front" in body["data"]["passport_back"]["error"]
    assert body["data"]["g28"]["data"] is not None


def test_guardrail_rejection_is_slot_error(client):
    store = FakeStore()
    resp = post_extract(
        client, store,
        sequenced({"passport": [ValueError("too blurry — re-scan")], "g28": []}),
        files={"passport_front": ("f.png", PNG, "image/png")},
    )
    body = resp.json()
    assert body["success"] is True
    assert "blurry" in body["data"]["passport"]["error"]


def test_storage_failure_degrades_to_warning(client):
    store = FakeStore(fail=True)
    front = envelope("passport", passport_data(surname="GARCIA"))
    resp = post_extract(
        client, store, sequenced({"passport": [front], "g28": []}),
        files={"passport_front": ("f.png", PNG, "image/png")},
    )
    body = resp.json()
    assert body["success"] is True  # extraction survives the storage outage
    warnings = body["data"]["passport"]["warnings"]
    assert any(w["field"] == "storage" for w in warnings)
    assert "storage down" not in str(body)  # no infra detail to the client


def test_no_files_rejected(client):
    resp = TestClient(m.app).post("/api/extract")
    body = resp.json()
    assert body["success"] is False
    assert "at least" in body["error"]


def test_artifact_download_unknown_id_is_404(client):
    resp = client.get("/api/population-artifact/" + "a" * 64)
    assert resp.status_code == 404
    body = resp.json()
    assert body["success"] is False
    assert "artifact" in body["error"].lower()


def test_artifact_download_rejects_malformed_ids(client):
    # Traversal-shaped and non-hash ids must 404 without touching the fs
    # (an embedded slash is a different route → 404 from the router itself).
    for bad in ("A" * 64, "zz", "%2e%2e%2fetc%2fpasswd"):
        resp = client.get(f"/api/population-artifact/{bad}")
        assert resp.status_code == 404, bad


def test_artifact_serves_pdf_inline_for_viewing(client, tmp_path, monkeypatch):
    artifact = tmp_path / ("b" * 64 + ".a28.pdf")
    artifact.write_bytes(b"%PDF-1.4 fake artifact")
    monkeypatch.setattr(m, "stored_artifact_path", lambda _id: artifact)
    resp = client.get("/api/population-artifact/" + "b" * 64)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"].startswith("inline")
    assert resp.content.startswith(b"%PDF")


def test_artifact_download_param_forces_attachment(client, tmp_path, monkeypatch):
    artifact = tmp_path / ("b" * 64 + ".a28.pdf")
    artifact.write_bytes(b"%PDF-1.4 fake artifact")
    monkeypatch.setattr(m, "stored_artifact_path", lambda _id: artifact)
    resp = client.get("/api/population-artifact/" + "b" * 64 + "?download=1")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment")
    assert "a28-filled.pdf" in resp.headers["content-disposition"]
