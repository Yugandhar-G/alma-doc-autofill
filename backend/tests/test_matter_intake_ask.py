"""Ask-the-matter offline: pure ref audit (strip / cannot-substantiate /
unanswerable), grant-block regression, an end-to-end run, and the HTTP endpoint
(firm-scoped, matter-not-found). Scripted model + faked distillation."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.kernel.agent import AgentBudget, AgentTranscript, run_tool_loop
from app.kernel.config import Settings, get_settings
from app.kernel.store.base import get_matter_store
from app.kernel.tools.registry import ToolContext
from app.main import create_app
from app.packages.matter_intake import ask, loop
from app.packages.matter_intake.package import PACKAGE as MATTER_INTAKE_PACKAGE
from app.packages.matter_intake.schemas import ResearchAnswer
from tests.matter_intake_util import bootstrap, make_store, scripted, tool_call_msg


# --- Pure ref audit --------------------------------------------------------
def test_audit_strips_unseen_refs() -> None:
    answer = ResearchAnswer(text="Yes.", refs=["seen", "ghost"], unanswerable=False)
    audited = ask.audit_answer(answer, seen_refs=["seen"])
    assert audited.refs == ["seen"]
    assert audited.text == "Yes."


def test_audit_all_stripped_becomes_cannot_substantiate() -> None:
    """Every ref invented → refuse honestly rather than return ungrounded text
    (the null-discipline analog)."""
    answer = ResearchAnswer(text="Confident but ungrounded.", refs=["ghost"], unanswerable=False)
    audited = ask.audit_answer(answer, seen_refs=["real"])
    assert audited.refs == []
    assert audited.unanswerable is True
    assert "could not substantiate" in audited.text


def test_audit_honors_unanswerable() -> None:
    answer = ResearchAnswer(text="No records cover that.", refs=[], unanswerable=True)
    audited = ask.audit_answer(answer, seen_refs=[])
    assert audited.unanswerable is True
    assert audited.text == "No records cover that."  # honest 'no' is preserved


# --- Grant-block regression (MANDATORY) ------------------------------------
async def test_ask_grants_block_non_granted_tools() -> None:
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
        emit=lambda _e: None, node="ask_matter",
    )
    await run_tool_loop(
        model=scripted(*turns), task_prompt="p",
        tools=loop.granted_registry(ask._GRANTS),
        budget=AgentBudget(max_tool_calls=12), ctx=ctx,
    )
    assert transcript.tool_calls == 0


# --- End-to-end run --------------------------------------------------------
async def test_ask_matter_end_to_end_audits_refs(tmp_path: Path, monkeypatch) -> None:
    store = make_store(tmp_path)
    scope, _ = await bootstrap(store)
    matter = await store.create_matter(scope, "immigration", "Petition")
    doc = await store.add_document(scope, matter.id, "a" * 64, "passport", "p.pdf")

    turns = [
        tool_call_msg(("list_matter_docs", {"matter_id": matter.id})),
        AIMessage(content="done."),
    ]
    monkeypatch.setattr(loop, "make_agent_model", lambda settings, live=False: scripted(*turns))
    monkeypatch.setattr(loop, "make_client", lambda s: None)

    async def fake_call_gemini(client, model, prompt, wrapper, settings, **kwargs):
        assert wrapper is ResearchAnswer
        return ResearchAnswer(
            text="The matter has a passport on file.", refs=[doc.doc_id, "ghost"], unanswerable=False
        )

    monkeypatch.setattr(loop, "call_gemini", fake_call_gemini)

    answer = await ask.ask_matter(
        scope, matter.id, "What documents are on file?", Settings(_env_file=None), store
    )
    assert answer.refs == [doc.doc_id]  # ghost stripped; real doc_id survived (it was seen)
    assert "passport" in answer.text


# --- HTTP endpoint ---------------------------------------------------------
@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    settings = Settings(
        _env_file=None,
        matter_store_path=str(tmp_path / "matters.db"),
        local_storage_dir=str(tmp_path / "blobs"),
    )
    store = make_store(tmp_path)
    app = create_app(registry=(MATTER_INTAKE_PACKAGE,))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_matter_store] = lambda: store

    async def fake_ask(scope, matter_id, question, s, st):
        return ResearchAnswer(text="stub", refs=[], unanswerable=False)

    # The endpoint's agent is exercised by the end-to-end test above; here we
    # verify routing, scoping, and not-found, so the agent call is stubbed.
    monkeypatch.setattr("app.packages.matter_intake.router.ask_matter", fake_ask)
    with TestClient(app) as c:
        yield c, store


async def test_ask_endpoint_matter_not_found(client) -> None:
    c, _ = client
    resp = c.post("/api/packages/matter_intake/matters/nope/ask", json={"question": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False and "not found" in body["error"].lower()


async def test_ask_endpoint_happy_path(client) -> None:
    c, store = client
    # In no-account local mode the dev principal is auto-provisioned; create a
    # matter under that same firm via the store the app shares.
    from app.kernel.auth import _local_principal, scope_of

    principal = await _local_principal(store)
    scope = scope_of(principal)
    matter = await store.create_matter(scope, "immigration", "Petition")

    resp = c.post(
        f"/api/packages/matter_intake/matters/{matter.id}/ask", json={"question": "what is on file?"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["text"] == "stub"
