"""Offline tests for the firm-scoped matter store (SQLite impl on tmp_path).

Covers: full CRUD round-trips for every entity, the tenancy wall (firm B can
reach NOTHING of firm A's), run status transitions, interrupt create→resolve,
memory list filtering (matter_type + criterion_key + limit, newest first), the
thread_id_for namespace format, and public method-signature parity between the
SQLite and Supabase implementations (the offline proxy for the un-testable
Supabase path).
"""
import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.kernel.config import Settings
from app.kernel.store.base import MatterStore, TenantScope, thread_id_for
from app.kernel.store.sqlite_store import SqliteMatterStore
from app.kernel.store.supabase_store import SupabaseMatterStore


@pytest.fixture
def store(tmp_path: Path) -> SqliteMatterStore:
    return SqliteMatterStore(
        Settings(_env_file=None, matter_store_path=str(tmp_path / "matters.db"))
    )


async def _bootstrap(store: SqliteMatterStore) -> tuple[TenantScope, TenantScope]:
    """Two independent firms, each with one user. Returns (scope_a, scope_b)."""
    firm_a = await store.create_firm("Alpha LLP")
    firm_b = await store.create_firm("Beta PC")
    user_a = await store.create_user(firm_a.id, "a@alpha.test", "attorney", "auth-a")
    user_b = await store.create_user(firm_b.id, "b@beta.test", "staff", "auth-b")
    return (
        TenantScope(firm_id=firm_a.id, user_id=user_a.id),
        TenantScope(firm_id=firm_b.id, user_id=user_b.id),
    )


# --- Firm bootstrap --------------------------------------------------------
async def test_create_firm_mints_id_and_timestamp(store: SqliteMatterStore) -> None:
    firm = await store.create_firm("Alpha LLP")
    assert firm.id and len(firm.id) == 32
    assert firm.name == "Alpha LLP"
    assert firm.created_at.tzinfo is not None


async def test_user_round_trip_by_auth_id(store: SqliteMatterStore) -> None:
    firm = await store.create_firm("Alpha LLP")
    created = await store.create_user(firm.id, "a@alpha.test", "admin", "auth-xyz")
    fetched = await store.get_user_by_auth_id("auth-xyz")
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.role == "admin"
    assert fetched.firm_id == firm.id


async def test_get_user_by_unknown_auth_id_returns_none(store: SqliteMatterStore) -> None:
    assert await store.get_user_by_auth_id("nope") is None


# --- Matter CRUD -----------------------------------------------------------
async def test_matter_round_trip(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "Dr. X petition", client_ref="CR-1")
    assert matter.status == "open"
    assert matter.created_by == scope_a.user_id
    assert matter.firm_id == scope_a.firm_id
    fetched = await store.get_matter(scope_a, matter.id)
    assert fetched is not None and fetched.model_dump() == matter.model_dump()
    listed = await store.list_matters(scope_a)
    assert [m.id for m in listed] == [matter.id]


async def test_list_matters_newest_first(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    first = await store.create_matter(scope_a, "o1a", "first")
    second = await store.create_matter(scope_a, "eb1a", "second")
    third = await store.create_matter(scope_a, "o1a", "third")
    listed = await store.list_matters(scope_a)
    assert [m.id for m in listed] == [third.id, second.id, first.id]


# --- Document CRUD ---------------------------------------------------------
async def test_document_round_trip(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    doc = await store.add_document(scope_a, matter.id, "a" * 64, "passport", "p.pdf")
    assert doc.uploaded_by == scope_a.user_id
    assert doc.firm_id == scope_a.firm_id
    listed = await store.list_documents(scope_a, matter.id)
    assert [d.id for d in listed] == [doc.id]
    assert listed[0].doc_id == "a" * 64


async def test_add_document_to_foreign_matter_fails_loud(store: SqliteMatterStore) -> None:
    scope_a, scope_b = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    with pytest.raises(ValueError, match="not found in firm"):
        await store.add_document(scope_b, matter.id, "a" * 64, "passport", "p.pdf")


# --- Run lifecycle ---------------------------------------------------------
async def test_run_round_trip_and_thread_id(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    run = await store.create_run(scope_a, matter.id, "screener")
    assert run.status == "queued"
    assert run.thread_id == thread_id_for(scope_a.firm_id, matter.id, run.id)
    assert run.finished_at is None
    fetched = await store.get_run(scope_a, run.id)
    assert fetched is not None and fetched.id == run.id


async def test_update_run_status_transitions_and_summary_merge(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    run = await store.create_run(scope_a, matter.id, "screener")

    running = await store.update_run_status(scope_a, run.id, "running", {"step": 1})
    assert running.status == "running"
    assert running.summary_json == {"step": 1}
    assert running.finished_at is None

    done = await store.update_run_status(
        scope_a, run.id, "done", {"verdict": "likely"}, finished_at_now=True
    )
    assert done.status == "done"
    # merge, not replace
    assert done.summary_json == {"step": 1, "verdict": "likely"}
    assert done.finished_at is not None


async def test_list_runs_by_matter_and_by_firm_status(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    m1 = await store.create_matter(scope_a, "o1a", "one")
    m2 = await store.create_matter(scope_a, "eb1a", "two")
    r1 = await store.create_run(scope_a, m1.id, "screener")
    r2 = await store.create_run(scope_a, m2.id, "autofill")
    await store.update_run_status(scope_a, r2.id, "running")

    by_matter = await store.list_runs(scope_a, matter_id=m1.id)
    assert [r.id for r in by_matter] == [r1.id]

    queued = await store.list_runs(scope_a, status="queued")
    assert [r.id for r in queued] == [r1.id]
    running = await store.list_runs(scope_a, status="running")
    assert [r.id for r in running] == [r2.id]

    all_firm = await store.list_runs(scope_a)
    assert {r.id for r in all_firm} == {r1.id, r2.id}


async def test_update_missing_run_fails_loud(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    with pytest.raises(ValueError, match="not found in firm"):
        await store.update_run_status(scope_a, "deadbeef", "done")


# --- Artifacts -------------------------------------------------------------
async def test_artifact_round_trip(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    run = await store.create_run(scope_a, matter.id, "autofill")
    art = await store.add_artifact(scope_a, run.id, "population_pdf", "hash-123")
    listed = await store.list_artifacts(scope_a, run.id)
    assert [a.id for a in listed] == [art.id]
    assert listed[0].kind == "population_pdf"
    assert listed[0].artifact_ref == "hash-123"


# --- Interrupts ------------------------------------------------------------
async def test_interrupt_create_and_resolve(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    run = await store.create_run(scope_a, matter.id, "screener")
    interrupt = await store.create_interrupt(
        scope_a, run.id, "review", "review_gate", {"matrix": [1, 2]}
    )
    assert interrupt.status == "pending"
    assert interrupt.payload_json == {"matrix": [1, 2]}
    assert interrupt.resolved_at is None

    pending = await store.list_interrupts(scope_a, status="pending")
    assert [i.id for i in pending] == [interrupt.id]

    resolved = await store.resolve_interrupt(scope_a, interrupt.id, scope_a.user_id)
    assert resolved.status == "resolved"
    assert resolved.resolved_by == scope_a.user_id
    assert resolved.resolved_at is not None

    assert await store.list_interrupts(scope_a, status="pending") == []
    still_there = await store.list_interrupts(scope_a, status="resolved")
    assert [i.id for i in still_there] == [interrupt.id]


async def test_resolve_missing_interrupt_fails_loud(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    with pytest.raises(ValueError, match="not found in firm"):
        await store.resolve_interrupt(scope_a, "deadbeef", scope_a.user_id)


# --- Memory ----------------------------------------------------------------
async def test_memory_round_trip(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    record = await store.add_memory(
        scope_a, matter.id, "o1a", "rfe", "RFE on awards",
        {"paras": 3}, run_id=None, criterion_key="awards",
    )
    assert record.firm_id == scope_a.firm_id
    listed = await store.list_memories(scope_a)
    assert [m.id for m in listed] == [record.id]
    assert listed[0].detail_json == {"paras": 3}


async def test_memory_filtering_by_type_and_criterion(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    await store.add_memory(scope_a, matter.id, "o1a", "rfe", "one", {}, criterion_key="awards")
    await store.add_memory(scope_a, matter.id, "o1a", "denial", "two", {}, criterion_key="press")
    await store.add_memory(scope_a, matter.id, "eb1a", "approval", "three", {}, criterion_key="awards")

    o1a = await store.list_memories(scope_a, matter_type="o1a")
    assert {m.summary for m in o1a} == {"one", "two"}

    awards = await store.list_memories(scope_a, matter_type="o1a", criterion_key="awards")
    assert [m.summary for m in awards] == ["one"]


async def test_memory_list_newest_first_and_limit(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    for label in ("m1", "m2", "m3"):
        await store.add_memory(scope_a, matter.id, "o1a", "outcome_note", label, {})
    limited = await store.list_memories(scope_a, limit=2)
    assert [m.summary for m in limited] == ["m3", "m2"]


# --- The tenancy wall ------------------------------------------------------
async def test_tenancy_wall_blocks_all_cross_firm_reads(store: SqliteMatterStore) -> None:
    """Firm B's scope must reach NONE of firm A's rows across every entity."""
    scope_a, scope_b = await _bootstrap(store)

    matter = await store.create_matter(scope_a, "o1a", "confidential", client_ref="SECRET")
    await store.add_document(scope_a, matter.id, "a" * 64, "passport", "p.pdf")
    run = await store.create_run(scope_a, matter.id, "screener")
    await store.add_artifact(scope_a, run.id, "report", "ref-1")
    interrupt = await store.create_interrupt(scope_a, run.id, "review", "gate", {})
    await store.add_memory(scope_a, matter.id, "o1a", "rfe", "secret memory", {})

    # get returns None across the wall
    assert await store.get_matter(scope_b, matter.id) is None
    assert await store.get_run(scope_b, run.id) is None

    # list returns empty across the wall
    assert await store.list_matters(scope_b) == []
    assert await store.list_documents(scope_b, matter.id) == []
    assert await store.list_runs(scope_b, matter_id=matter.id) == []
    assert await store.list_runs(scope_b, status="queued") == []
    assert await store.list_artifacts(scope_b, run.id) == []
    assert await store.list_interrupts(scope_b) == []
    assert await store.list_memories(scope_b) == []
    assert await store.list_memories(scope_b, matter_type="o1a") == []

    # mutations across the wall fail loud (no silent no-op)
    with pytest.raises(ValueError, match="not found in firm"):
        await store.update_run_status(scope_b, run.id, "done")
    with pytest.raises(ValueError, match="not found in firm"):
        await store.resolve_interrupt(scope_b, interrupt.id, scope_b.user_id)

    # firm A still sees everything (the wall is one-directional isolation,
    # not global breakage)
    assert await store.get_matter(scope_a, matter.id) is not None
    assert len(await store.list_memories(scope_a)) == 1


# --- Helpers & invariants --------------------------------------------------
def test_thread_id_for_format() -> None:
    assert thread_id_for("F1", "M2", "R3") == "F1:M2:R3"


def test_tenant_scope_is_frozen() -> None:
    scope = TenantScope(firm_id="F1", user_id="U1")
    with pytest.raises(FrozenInstanceError):
        scope.firm_id = "F2"  # type: ignore[misc]


def _public_async_methods(cls: type) -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(fn)
        for name, fn in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    }


def test_impls_expose_identical_public_signatures() -> None:
    """The Supabase path can't be integration-tested offline; assert instead
    that it never drifts from the SQLite path's public contract (both against
    the ABC)."""
    abstract = {
        name for name, value in vars(MatterStore).items()
        if getattr(value, "__isabstractmethod__", False)
    }
    sqlite = _public_async_methods(SqliteMatterStore)
    supabase = _public_async_methods(SupabaseMatterStore)

    # every abstract method is implemented by both, with identical signatures
    assert abstract <= set(sqlite)
    assert abstract <= set(supabase)
    for name in abstract:
        assert sqlite[name] == supabase[name], f"signature drift on {name}"
