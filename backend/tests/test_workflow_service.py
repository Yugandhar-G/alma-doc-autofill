"""WorkflowService + Scheduler tests — the run lifecycle over a REAL package
graph (preflight, zero-LLM) plus the scheduler's concurrency gate.

Offline: tmp matter-store DB + tmp checkpoint DB via injected Settings; no
network, no key. The preflight graph parks at review_gate on ainvoke and
completes on resume, so the full queued → awaiting_input → resume → done arc
runs against production code, not a fake graph.
"""
import asyncio
import json
import types
from pathlib import Path

import pytest

from app.kernel.config import Settings
from app.kernel.runtime.scheduler import Scheduler
from app.kernel.runtime.workflows import WorkflowError, WorkflowService
from app.kernel.store.base import TenantScope
from app.kernel.store.sqlite_store import SqliteMatterStore
from app.packages.preflight.package import PACKAGE as PREFLIGHT_PACKAGE
from app.packages.preflight.state import PreflightState
from app.schemas import ExtractionEnvelope


# --- Fixtures --------------------------------------------------------------
def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        matter_store_path=str(tmp_path / "matters.db"),
        preflight_checkpoint_path=str(tmp_path / "preflight.db"),
        max_concurrent_runs_per_firm=2,
    )


@pytest.fixture
def store(tmp_path: Path) -> SqliteMatterStore:
    return SqliteMatterStore(_settings(tmp_path))


@pytest.fixture
def service(tmp_path: Path, store: SqliteMatterStore) -> WorkflowService:
    return WorkflowService(store, (PREFLIGHT_PACKAGE,), settings=_settings(tmp_path))


async def _two_firms(store: SqliteMatterStore) -> tuple[TenantScope, TenantScope]:
    firm_a = await store.create_firm("Alpha LLP")
    firm_b = await store.create_firm("Beta PC")
    user_a = await store.create_user(firm_a.id, "a@alpha.test", "attorney", "auth-a")
    user_b = await store.create_user(firm_b.id, "b@beta.test", "attorney", "auth-b")
    return (
        TenantScope(firm_id=firm_a.id, user_id=user_a.id),
        TenantScope(firm_id=firm_b.id, user_id=user_b.id),
    )


def _preflight_state() -> PreflightState:
    """A synthetic packet: one passport + one G-28 envelope (referenced by
    hash, no bytes). Enough for gather_packet → cross_checks → review."""
    return PreflightState(
        run_id="placeholder",
        case_type="g28_filing",
        envelopes=[
            ExtractionEnvelope(
                document_type_requested="passport",
                document_type_detected="passport",
                data={"surname": "DOE", "given_names": "JANE"},
                source_hash="a" * 64,
            ),
            ExtractionEnvelope(
                document_type_requested="g28",
                document_type_detected="g28",
                data={"attorney": {"last_name": "SMITH"}},
                source_hash="b" * 64,
            ),
        ],
    )


# --- Run lifecycle over the real preflight graph ---------------------------
async def test_start_run_parks_awaiting_with_interrupt_and_inbox(
    service: WorkflowService, store: SqliteMatterStore
) -> None:
    scope, _ = await _two_firms(store)
    matter = await store.create_matter(scope, "immigration", "Petition")

    run = await service.start_run(scope, matter.id, "preflight", _preflight_state())

    assert run.status == "awaiting_input"
    assert run.matter_id == matter.id
    assert run.package_id == "preflight"

    interrupts = await service.pending_interrupts(scope)
    assert len(interrupts) == 1
    parked = interrupts[0]
    assert parked.run_id == run.id
    assert parked.kind == "preflight_review"  # manifest.interrupt_kinds[0]
    assert parked.node == "review_gate"
    assert parked.status == "pending"
    assert "report" in parked.payload_json  # the draft the reviewer must see


async def test_start_run_stamps_authoritative_run_id_on_state(
    service: WorkflowService, store: SqliteMatterStore
) -> None:
    scope, _ = await _two_firms(store)
    matter = await store.create_matter(scope, "immigration", "Petition")
    run = await service.start_run(scope, matter.id, "preflight", _preflight_state())
    # thread_id is firm:matter:run — the run id the store minted, not the
    # placeholder the caller passed.
    assert run.thread_id.endswith(f":{run.id}")
    assert run.thread_id.startswith(f"{scope.firm_id}:{matter.id}:")


async def test_resume_completes_run_with_report_artifact(
    service: WorkflowService, store: SqliteMatterStore
) -> None:
    scope, _ = await _two_firms(store)
    matter = await store.create_matter(scope, "immigration", "Petition")
    run = await service.start_run(scope, matter.id, "preflight", _preflight_state())

    # Approve the draft unchanged (findings=None keeps the battery's findings).
    report = await service.resume_run(scope, run.id, {"findings": None})

    assert report  # the final report dump
    assert report["case_type"] == "g28_filing"

    settled = await service.run_status(scope, run.id)
    assert settled is not None and settled.status == "done"
    assert settled.finished_at is not None

    artifacts = await store.list_artifacts(scope, run.id)
    report_artifacts = [a for a in artifacts if a.kind == "report"]
    assert len(report_artifacts) == 1
    persisted = json.loads(report_artifacts[0].artifact_ref)
    assert persisted["case_type"] == "g28_filing"
    assert "findings" in persisted and "checks_run" in persisted


async def test_resume_resolves_the_interrupt_row(
    service: WorkflowService, store: SqliteMatterStore
) -> None:
    scope, _ = await _two_firms(store)
    matter = await store.create_matter(scope, "immigration", "Petition")
    run = await service.start_run(scope, matter.id, "preflight", _preflight_state())
    await service.resume_run(scope, run.id, {"findings": None})

    assert await service.pending_interrupts(scope) == []
    resolved = await store.list_interrupts(scope, status="resolved")
    assert len(resolved) == 1
    assert resolved[0].run_id == run.id
    assert resolved[0].resolved_by == scope.user_id


# --- Error paths -----------------------------------------------------------
async def test_resume_non_awaiting_run_refused(
    service: WorkflowService, store: SqliteMatterStore
) -> None:
    scope, _ = await _two_firms(store)
    matter = await store.create_matter(scope, "immigration", "Petition")
    run = await service.start_run(scope, matter.id, "preflight", _preflight_state())
    await service.resume_run(scope, run.id, {"findings": None})  # → done

    with pytest.raises(WorkflowError, match="awaiting"):
        await service.resume_run(scope, run.id, {"findings": None})


async def test_resume_unknown_run_refused(
    service: WorkflowService, store: SqliteMatterStore
) -> None:
    scope, _ = await _two_firms(store)
    with pytest.raises(WorkflowError, match="not found"):
        await service.resume_run(scope, "no-such-run", {"findings": None})


async def test_cross_firm_resume_refused(
    service: WorkflowService, store: SqliteMatterStore
) -> None:
    scope_a, scope_b = await _two_firms(store)
    matter = await store.create_matter(scope_a, "immigration", "Petition")
    run = await service.start_run(scope_a, matter.id, "preflight", _preflight_state())

    # Firm B cannot see, let alone resume, firm A's parked run.
    with pytest.raises(WorkflowError, match="not found"):
        await service.resume_run(scope_b, run.id, {"findings": None})
    # And firm A's interrupt is invisible to firm B's inbox.
    assert await service.pending_interrupts(scope_b) == []


async def test_start_run_unknown_matter_refused(
    service: WorkflowService, store: SqliteMatterStore
) -> None:
    scope, _ = await _two_firms(store)
    with pytest.raises(WorkflowError, match="matter not found"):
        await service.start_run(scope, "no-such-matter", "preflight", _preflight_state())


async def test_start_run_unknown_package_refused(
    service: WorkflowService, store: SqliteMatterStore
) -> None:
    scope, _ = await _two_firms(store)
    matter = await store.create_matter(scope, "immigration", "Petition")
    with pytest.raises(WorkflowError, match="unknown package"):
        await service.start_run(scope, matter.id, "nope", _preflight_state())


# --- Reconciliation --------------------------------------------------------
async def test_reconcile_expires_orphaned_interrupt(
    service: WorkflowService, store: SqliteMatterStore
) -> None:
    scope, _ = await _two_firms(store)
    matter = await store.create_matter(scope, "immigration", "Petition")
    # Fabricate an awaiting run with NO parked checkpoint thread — the graph
    # was never invoked, so the checkpointer holds nothing to resume.
    run = await store.create_run(scope, matter.id, "preflight")
    await store.update_run_status(scope, run.id, "awaiting_input")
    await store.create_interrupt(
        scope, run.id, "preflight_review", "review_gate", {"report": None}
    )

    expired = await service.reconcile(scope)

    assert expired == 1
    assert await service.pending_interrupts(scope) == []
    orphaned = await store.list_interrupts(scope, status="expired")
    assert len(orphaned) == 1 and orphaned[0].run_id == run.id
    settled = await service.run_status(scope, run.id)
    assert settled is not None and settled.status == "error"


async def test_reconcile_leaves_genuinely_parked_run(
    service: WorkflowService, store: SqliteMatterStore
) -> None:
    scope, _ = await _two_firms(store)
    matter = await store.create_matter(scope, "immigration", "Petition")
    run = await service.start_run(scope, matter.id, "preflight", _preflight_state())

    expired = await service.reconcile(scope)

    assert expired == 0  # a real parked thread is not orphaned
    still_pending = await service.pending_interrupts(scope)
    assert len(still_pending) == 1 and still_pending[0].run_id == run.id


async def test_reconcile_none_scope_is_noop(service: WorkflowService) -> None:
    assert await service.reconcile(None) == 0


# --- Scheduler concurrency gate --------------------------------------------
def _fake_run(run_id: str):
    """The scheduler only reads run.id; a namespace is enough."""
    return types.SimpleNamespace(id=run_id)


async def test_scheduler_caps_concurrency_per_firm() -> None:
    sched = Scheduler(2)
    scope = TenantScope(firm_id="f1", user_id="u1")
    started = [asyncio.Event() for _ in range(3)]
    release = asyncio.Event()

    async def work(index: int) -> None:
        started[index].set()
        await release.wait()

    tasks = [
        await sched.enqueue(scope, _fake_run(f"r{i}"), lambda i=i: work(i))
        for i in range(3)
    ]
    await asyncio.sleep(0.05)  # let admitted tasks reach their event

    assert started[0].is_set() and started[1].is_set()  # cap = 2 admitted
    assert not started[2].is_set()  # third waits on a slot

    release.set()
    await asyncio.gather(*tasks)
    assert started[2].is_set()  # freed slot admits the third


async def test_scheduler_isolates_firms() -> None:
    """One firm saturating its 1-slot cap never blocks another firm's run."""
    sched = Scheduler(1)
    scope_a = TenantScope(firm_id="fa", user_id="ua")
    scope_b = TenantScope(firm_id="fb", user_id="ub")
    a_started = asyncio.Event()
    b_started = asyncio.Event()
    hold = asyncio.Event()

    async def blocker(ev: asyncio.Event) -> None:
        ev.set()
        await hold.wait()

    ta = await sched.enqueue(scope_a, _fake_run("a1"), lambda: blocker(a_started))
    # Firm A's second run fills nothing of firm B's independent slot.
    tb = await sched.enqueue(scope_b, _fake_run("b1"), lambda: blocker(b_started))
    await asyncio.sleep(0.05)

    assert a_started.is_set() and b_started.is_set()
    hold.set()
    await asyncio.gather(ta, tb)


async def test_scheduler_shutdown_cancels_inflight() -> None:
    sched = Scheduler(2)
    scope = TenantScope(firm_id="f1", user_id="u1")
    started = asyncio.Event()

    async def long_work() -> None:
        started.set()
        await asyncio.sleep(100)

    task = await sched.enqueue(scope, _fake_run("r1"), lambda: long_work())
    await asyncio.sleep(0.02)
    assert started.is_set()

    await sched.shutdown()
    assert task.cancelled()

    # After shutdown, enqueue refuses new work loudly.
    with pytest.raises(RuntimeError, match="shutting down"):
        await sched.enqueue(scope, _fake_run("r2"), lambda: long_work())
