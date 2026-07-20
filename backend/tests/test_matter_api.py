"""Matter API tests — the HTTP surface (matters, documents, runs, inbox) in
no-account local mode.

The app is built over a single installed package (preflight, zero-LLM) with a
tmp matter store + tmp checkpoint DB injected via dependency overrides. The
dev principal is auto-provisioned on first request (Supabase disabled), so no
tokens are needed. Firm isolation is proved at the service layer by constructing
a second scope directly against the same store and confirming the API-minted
rows are invisible to it.
"""
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.matters import get_workflow_service
from app.kernel.auth import get_principal, resolve_principal
from app.kernel.config import Settings, get_settings
from app.kernel.runtime.workflows import WorkflowService
from app.kernel.store.base import TenantScope, get_matter_store
from app.kernel.store.sqlite_store import SqliteMatterStore
from app.main import create_app
from app.packages.preflight.package import PACKAGE as PREFLIGHT_PACKAGE


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        matter_store_path=str(tmp_path / "matters.db"),
        preflight_checkpoint_path=str(tmp_path / "preflight.db"),
        local_storage_dir=str(tmp_path / "blobs"),
        max_concurrent_runs_per_firm=2,
    )


@pytest.fixture
def context(tmp_path: Path):
    """A TestClient wired to a tmp store + tmp-path WorkflowService, plus the
    shared store instance so tests can construct a rival firm scope."""
    settings = _settings(tmp_path)
    store = SqliteMatterStore(settings)
    service = WorkflowService(store, (PREFLIGHT_PACKAGE,), settings=settings)

    app = create_app(registry=(PREFLIGHT_PACKAGE,))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_matter_store] = lambda: store
    app.dependency_overrides[get_workflow_service] = lambda: service

    # Context-manage the client so every request shares ONE event loop — the
    # workflow graph's checkpointer connection is loop-bound, and a fresh loop
    # per request (the bare-constructor default) would orphan it on resume.
    with TestClient(app) as client:
        yield client, store, settings


def _ok(response) -> dict:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True, body
    return body["data"]


# --- Matter CRUD -----------------------------------------------------------
def test_create_and_get_matter(context) -> None:
    client, _, _ = context
    data = _ok(
        client.post(
            "/api/matters",
            json={"matter_type": "immigration", "title": "Dr. X petition", "client_ref": "CR-1"},
        )
    )
    matter = data["matter"]
    assert matter["matter_type"] == "immigration"
    assert matter["status"] == "open"
    assert matter["client_ref"] == "CR-1"

    fetched = _ok(client.get(f"/api/matters/{matter['id']}"))
    assert fetched["matter"]["id"] == matter["id"]
    assert fetched["documents"] == []
    assert fetched["runs"] == []


def test_list_matters_newest_first(context) -> None:
    client, _, _ = context
    first = _ok(client.post("/api/matters", json={"matter_type": "immigration", "title": "first"}))
    second = _ok(client.post("/api/matters", json={"matter_type": "immigration", "title": "second"}))
    data = _ok(client.get("/api/matters"))
    ids = [m["id"] for m in data["matters"]]
    assert ids == [second["matter"]["id"], first["matter"]["id"]]


def test_get_unknown_matter_404(context) -> None:
    client, _, _ = context
    resp = client.get("/api/matters/nope")
    assert resp.status_code == 404
    assert resp.json()["success"] is False


def test_create_matter_validation_error(context) -> None:
    client, _, _ = context
    resp = client.post("/api/matters", json={"matter_type": "", "title": ""})
    assert resp.status_code == 422  # pydantic body validation


# --- Document upload -------------------------------------------------------
def test_upload_documents_creates_rows(context) -> None:
    client, _, _ = context
    matter = _ok(client.post("/api/matters", json={"matter_type": "immigration", "title": "M"}))["matter"]

    files = [
        ("files", ("a.pdf", io.BytesIO(b"%PDF-1.4 fake bytes a"), "application/pdf")),
        ("files", ("b.png", io.BytesIO(b"\x89PNG fake bytes b"), "image/png")),
    ]
    data = _ok(client.post(f"/api/matters/{matter['id']}/documents", files=files, data={"doc_type": "passport"}))
    assert len(data["documents"]) == 2
    assert data["rejected"] == []
    assert {d["filename"] for d in data["documents"]} == {"a.pdf", "b.png"}
    assert all(d["doc_type"] == "passport" for d in data["documents"])

    fetched = _ok(client.get(f"/api/matters/{matter['id']}"))
    assert len(fetched["documents"]) == 2


def test_upload_documents_unknown_matter_404(context) -> None:
    client, _, _ = context
    files = [("files", ("a.pdf", io.BytesIO(b"bytes"), "application/pdf"))]
    resp = client.post("/api/matters/nope/documents", files=files)
    assert resp.status_code == 404


# --- Run lifecycle through the API -----------------------------------------
def _preflight_initial() -> dict:
    return {
        "case_type": "g28_filing",
        "envelopes": [
            {
                "document_type_requested": "passport",
                "document_type_detected": "passport",
                "data": {"surname": "DOE", "given_names": "JANE"},
                "source_hash": "a" * 64,
            }
        ],
    }


def test_run_lifecycle_start_inbox_resume_done(context) -> None:
    client, _, _ = context
    matter = _ok(client.post("/api/matters", json={"matter_type": "immigration", "title": "M"}))["matter"]

    run = _ok(
        client.post(
            f"/api/matters/{matter['id']}/runs",
            json={"package_id": "preflight", "initial": _preflight_initial()},
        )
    )["run"]
    assert run["status"] == "awaiting_input"
    assert run["package_id"] == "preflight"

    # The parked run shows in the firm inbox.
    inbox = _ok(client.get("/api/inbox"))["interrupts"]
    assert len(inbox) == 1
    assert inbox[0]["run_id"] == run["id"]
    assert inbox[0]["kind"] == "preflight_review"

    # GET run status reflects awaiting.
    status = _ok(client.get(f"/api/runs/{run['id']}"))
    assert status["run"]["status"] == "awaiting_input"
    assert status["artifacts"] == []

    # Resume approving the draft → done + report artifact.
    resumed = _ok(client.post(f"/api/runs/{run['id']}/resume", json={"payload": {"findings": None}}))
    assert resumed["run"]["status"] == "done"
    assert resumed["report"]["case_type"] == "g28_filing"

    final = _ok(client.get(f"/api/runs/{run['id']}"))
    report_artifacts = [a for a in final["artifacts"] if a["kind"] == "report"]
    assert len(report_artifacts) == 1
    assert json.loads(report_artifacts[0]["artifact_ref"])["case_type"] == "g28_filing"

    # Inbox now empty (interrupt resolved).
    assert _ok(client.get("/api/inbox"))["interrupts"] == []


def test_start_run_invalid_initial_400(context) -> None:
    client, _, _ = context
    matter = _ok(client.post("/api/matters", json={"matter_type": "immigration", "title": "M"}))["matter"]
    # envelopes must be a list of envelope shapes, not a bare string.
    resp = client.post(
        f"/api/matters/{matter['id']}/runs",
        json={"package_id": "preflight", "initial": {"envelopes": "not-a-list"}},
    )
    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_start_run_unknown_package_404(context) -> None:
    client, _, _ = context
    matter = _ok(client.post("/api/matters", json={"matter_type": "immigration", "title": "M"}))["matter"]
    resp = client.post(
        f"/api/matters/{matter['id']}/runs",
        json={"package_id": "ghost", "initial": {}},
    )
    assert resp.status_code == 404


def test_start_run_unknown_matter_404(context) -> None:
    client, _, _ = context
    resp = client.post(
        "/api/matters/nope/runs",
        json={"package_id": "preflight", "initial": _preflight_initial()},
    )
    assert resp.status_code == 404


def test_resume_non_awaiting_run_409(context) -> None:
    client, _, _ = context
    matter = _ok(client.post("/api/matters", json={"matter_type": "immigration", "title": "M"}))["matter"]
    run = _ok(
        client.post(
            f"/api/matters/{matter['id']}/runs",
            json={"package_id": "preflight", "initial": _preflight_initial()},
        )
    )["run"]
    client.post(f"/api/runs/{run['id']}/resume", json={"payload": {"findings": None}})  # → done
    resp = client.post(f"/api/runs/{run['id']}/resume", json={"payload": {"findings": None}})
    assert resp.status_code == 409
    assert resp.json()["success"] is False


def test_resume_unknown_run_404(context) -> None:
    client, _, _ = context
    resp = client.post("/api/runs/nope/resume", json={"payload": {}})
    assert resp.status_code == 404


def test_get_unknown_run_404(context) -> None:
    client, _, _ = context
    resp = client.get("/api/runs/nope")
    assert resp.status_code == 404


# --- Firm isolation (API-minted rows invisible to a rival firm) ------------
async def test_firm_isolation_across_scopes(context) -> None:
    client, store, settings = context
    # The API acts as the auto-provisioned local principal (firm A).
    matter = _ok(client.post("/api/matters", json={"matter_type": "immigration", "title": "Private"}))["matter"]
    run = _ok(
        client.post(
            f"/api/matters/{matter['id']}/runs",
            json={"package_id": "preflight", "initial": _preflight_initial()},
        )
    )["run"]

    # Construct a genuinely separate firm B directly against the same store.
    firm_b = await store.create_firm("Beta PC")
    user_b = await store.create_user(firm_b.id, "b@beta.test", "attorney", "auth-b")
    scope_b = TenantScope(firm_id=firm_b.id, user_id=user_b.id)

    # Firm B sees none of firm A's matters, runs, or interrupts.
    assert await store.list_matters(scope_b) == []
    assert await store.get_matter(scope_b, matter["id"]) is None
    assert await store.get_run(scope_b, run["id"]) is None
    assert await store.list_interrupts(scope_b, status="pending") == []


async def test_api_principal_is_firm_a_only(context) -> None:
    """Sanity: the local principal the API runs as owns exactly what it created
    — the rival scope constructed above is a real second firm, not the same one."""
    client, store, settings = context
    _ok(client.post("/api/matters", json={"matter_type": "immigration", "title": "A"}))
    principal = await resolve_principal(None, settings, store)
    scope_a = TenantScope(firm_id=principal.firm_id, user_id=principal.user_id)
    assert len(await store.list_matters(scope_a)) == 1
