"""Firm-data tool layer — deterministic retrieval, structural firm scoping, and
transcript ground truth. Offline: SQLite matter store on tmp_path + a fake
content-addressed doc store (monkeypatched over the get_store seam). No LLM."""
from pathlib import Path

import pytest

import app.kernel.tools.corpus as corpus
from app.kernel.agent import AgentTranscript
from app.kernel.config import Settings
from app.kernel.memory.service import MemoryService
from app.kernel.store.base import TenantScope
from app.kernel.store.sqlite_store import SqliteMatterStore
from app.kernel.tools.registry import ToolContext
from app.schemas import ExtractionEnvelope

TOOLS = {spec.name: spec for spec in corpus.CORPUS_TOOLS}


class _FakeDocStore:
    """Content-addressed extraction store keyed by (doc_id, doc_type, kind)."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str, str], ExtractionEnvelope] = {}

    def put(self, doc_id: str, doc_type: str, kind: str, envelope: ExtractionEnvelope) -> None:
        self._store[(doc_id, doc_type, kind)] = envelope

    async def get_extraction(self, doc_id: str, doc_type: str, kind: str = "raw"):
        return self._store.get((doc_id, doc_type, kind))


@pytest.fixture
def store(tmp_path: Path) -> SqliteMatterStore:
    return SqliteMatterStore(
        Settings(_env_file=None, matter_store_path=str(tmp_path / "matters.db"))
    )


@pytest.fixture
def doc_store(monkeypatch) -> _FakeDocStore:
    fake = _FakeDocStore()
    monkeypatch.setattr(corpus, "get_store", lambda: fake)
    return fake


async def _bootstrap(store: SqliteMatterStore) -> tuple[TenantScope, TenantScope]:
    firm_a = await store.create_firm("Alpha LLP")
    firm_b = await store.create_firm("Beta PC")
    user_a = await store.create_user(firm_a.id, "a@alpha.test", "attorney", "auth-a")
    user_b = await store.create_user(firm_b.id, "b@beta.test", "staff", "auth-b")
    return (
        TenantScope(firm_id=firm_a.id, user_id=user_a.id),
        TenantScope(firm_id=firm_b.id, user_id=user_b.id),
    )


def _ctx(store: SqliteMatterStore, scope: TenantScope | None) -> tuple[ToolContext, AgentTranscript]:
    transcript = AgentTranscript()
    ctx = ToolContext(
        settings=Settings(_env_file=None),
        transcript=transcript,
        emit=lambda _event: None,
        node="firm_data",
        scope=scope,
        matter_store=store if scope is not None else None,
        memory=MemoryService(store) if scope is not None else None,
    )
    return ctx, transcript


# --- Guard: no firm scope --------------------------------------------------
@pytest.mark.parametrize("name", list(TOOLS))
async def test_every_tool_refuses_without_firm_scope(store: SqliteMatterStore, name: str) -> None:
    ctx, _ = _ctx(store, scope=None)
    result = await TOOLS[name].run({"matter_id": "x", "doc_id": "x", "doc_type": "passport",
                                    "run_id": "x", "query": "x"}, ctx)
    assert result == "TOOL_UNAVAILABLE: no firm scope"


# --- list_matter_docs ------------------------------------------------------
async def test_list_matter_docs_happy_path_records_doc_ids(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    await store.add_document(scope_a, matter.id, "a" * 64, "passport", "passport.pdf")
    ctx, transcript = _ctx(store, scope_a)

    result = await TOOLS["list_matter_docs"].run({"matter_id": matter.id}, ctx)
    assert "a" * 64 in result
    assert "passport.pdf" in result
    assert transcript.seen_refs == ["a" * 64]
    assert any("list_matter_docs" in line for line in transcript.log)


# --- read_extraction -------------------------------------------------------
async def test_read_extraction_prefers_final_and_records_ref(
    store: SqliteMatterStore, doc_store: _FakeDocStore
) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    doc_id = "c" * 64
    await store.add_document(scope_a, matter.id, doc_id, "passport", "p.pdf")
    doc_store.put(doc_id, "passport", "final",
                  ExtractionEnvelope(document_type_requested="passport", data={"surname": "FINAL"}))
    doc_store.put(doc_id, "passport", "raw",
                  ExtractionEnvelope(document_type_requested="passport", data={"surname": "RAW"}))
    ctx, transcript = _ctx(store, scope_a)

    result = await TOOLS["read_extraction"].run({"doc_id": doc_id, "doc_type": "passport"}, ctx)
    assert "FINAL" in result and "RAW" not in result
    assert transcript.seen_refs == [doc_id]


async def test_read_extraction_falls_back_to_raw(
    store: SqliteMatterStore, doc_store: _FakeDocStore
) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    doc_id = "d" * 64
    await store.add_document(scope_a, matter.id, doc_id, "passport", "p.pdf")
    doc_store.put(doc_id, "passport", "raw",
                  ExtractionEnvelope(document_type_requested="passport", data={"surname": "RAW"}))
    ctx, _ = _ctx(store, scope_a)
    result = await TOOLS["read_extraction"].run({"doc_id": doc_id, "doc_type": "passport"}, ctx)
    assert "RAW" in result


async def test_read_extraction_refuses_doc_not_in_firm(
    store: SqliteMatterStore, doc_store: _FakeDocStore
) -> None:
    """Content-addressed blobs are not firm-scoped; the tool enforces the wall
    by requiring the doc_id to be indexed under the caller's matters."""
    scope_a, scope_b = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    doc_id = "e" * 64
    await store.add_document(scope_a, matter.id, doc_id, "passport", "p.pdf")
    doc_store.put(doc_id, "passport", "final",
                  ExtractionEnvelope(document_type_requested="passport", data={"x": 1}))

    ctx_b, transcript_b = _ctx(store, scope_b)  # firm B knows the hash but not the matter
    result = await TOOLS["read_extraction"].run({"doc_id": doc_id, "doc_type": "passport"}, ctx_b)
    assert result.startswith("NOT_FOUND")
    assert transcript_b.seen_refs == []


async def test_read_extraction_missing_is_not_found(
    store: SqliteMatterStore, doc_store: _FakeDocStore
) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    doc_id = "f" * 64
    await store.add_document(scope_a, matter.id, doc_id, "passport", "p.pdf")
    ctx, _ = _ctx(store, scope_a)  # nothing stored in the doc store
    result = await TOOLS["read_extraction"].run({"doc_id": doc_id, "doc_type": "passport"}, ctx)
    assert result.startswith("NOT_FOUND")


async def test_read_extraction_is_length_capped(
    store: SqliteMatterStore, doc_store: _FakeDocStore
) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    doc_id = "1" * 64
    await store.add_document(scope_a, matter.id, doc_id, "passport", "p.pdf")
    huge = {"blob": "z" * 20000}
    doc_store.put(doc_id, "passport", "final",
                  ExtractionEnvelope(document_type_requested="passport", data=huge))
    ctx, _ = _ctx(store, scope_a)
    result = await TOOLS["read_extraction"].run({"doc_id": doc_id, "doc_type": "passport"}, ctx)
    assert len(result) <= corpus._MAX_TOOL_CHARS + 32
    assert result.endswith("[truncated]")


# --- read_run_report -------------------------------------------------------
async def test_read_run_report_returns_summary(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    run = await store.create_run(scope_a, matter.id, "screener")
    await store.update_run_status(scope_a, run.id, "done", {"verdict": "likely"})
    ctx, transcript = _ctx(store, scope_a)

    result = await TOOLS["read_run_report"].run({"run_id": run.id}, ctx)
    assert "likely" in result
    assert transcript.seen_refs == [run.id]


async def test_read_run_report_cross_firm_is_not_found(store: SqliteMatterStore) -> None:
    scope_a, scope_b = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    run = await store.create_run(scope_a, matter.id, "screener")
    ctx_b, transcript_b = _ctx(store, scope_b)
    result = await TOOLS["read_run_report"].run({"run_id": run.id}, ctx_b)
    assert result.startswith("NOT_FOUND")
    assert transcript_b.seen_refs == []


# --- recall_memory ---------------------------------------------------------
async def test_recall_memory_renders_and_records_ids(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    memory = MemoryService(store)
    record = await memory.record(scope_a, matter_id=matter.id, run_id=None, matter_type="o1a",
                                 kind="rfe", summary="RFE on awards", criterion_key="awards")
    ctx, transcript = _ctx(store, scope_a)

    result = await TOOLS["recall_memory"].run({"matter_type": "o1a", "criterion_key": "awards"}, ctx)
    assert f"[memory:{record.id}]" in result
    assert transcript.seen_refs == [record.id]


async def test_recall_memory_cross_firm_returns_nothing(store: SqliteMatterStore) -> None:
    scope_a, scope_b = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    memory = MemoryService(store)
    await memory.record(scope_a, matter_id=matter.id, run_id=None, matter_type="o1a",
                        kind="rfe", summary="firm A only")
    ctx_b, transcript_b = _ctx(store, scope_b)
    result = await TOOLS["recall_memory"].run({}, ctx_b)
    assert result == "(no firm memory recalled)"
    assert transcript_b.seen_refs == []


# --- search_matter_corpus --------------------------------------------------
async def test_search_matter_corpus_matches_memory_and_docs(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    doc = await store.add_document(scope_a, matter.id, "9" * 64, "passport", "neurips_award.pdf")
    memory = MemoryService(store)
    mem = await memory.record(scope_a, matter_id=matter.id, run_id=None, matter_type="o1a",
                              kind="approval", summary="Approved on NeurIPS award evidence")
    ctx, transcript = _ctx(store, scope_a)

    result = await TOOLS["search_matter_corpus"].run({"query": "neurips"}, ctx)
    assert f"[memory:{mem.id}]" in result
    assert f"[doc:{doc.doc_id}]" in result
    assert set(transcript.seen_refs) == {mem.id, doc.doc_id}


async def test_search_matter_corpus_no_match(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    memory = MemoryService(store)
    await memory.record(scope_a, matter_id=matter.id, run_id=None, matter_type="o1a",
                        kind="rfe", summary="something unrelated")
    ctx, _ = _ctx(store, scope_a)
    result = await TOOLS["search_matter_corpus"].run({"query": "zzzznomatch"}, ctx)
    assert result.startswith("NO_MATCHES")


async def test_search_matter_corpus_is_firm_scoped(store: SqliteMatterStore) -> None:
    scope_a, scope_b = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    memory = MemoryService(store)
    await memory.record(scope_a, matter_id=matter.id, run_id=None, matter_type="o1a",
                        kind="approval", summary="Approved on NeurIPS award")
    ctx_b, transcript_b = _ctx(store, scope_b)
    result = await TOOLS["search_matter_corpus"].run({"query": "neurips"}, ctx_b)
    assert result.startswith("NO_MATCHES")
    assert transcript_b.seen_refs == []
