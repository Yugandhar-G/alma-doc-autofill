"""WorkflowService — the integration keystone tying the matter store, the
package runtime, and the scheduler into one run lifecycle.

A run is: verify the matter is in-firm → mint a WorkflowRun row (the durable
queue record) → drive the package's compiled graph through the Scheduler to
either a human-review interrupt or completion → reflect that outcome back into
the store (Interrupt row + awaiting_input, or done + a report RunArtifact, or
error). Resume feeds the human's payload back onto the same checkpointer thread
and settles the run the same way.

Streaming stays out of here by design. v1 drives graphs with `ainvoke`
(non-streaming), which is exactly right for the deterministic packages that
join the matter path first (autofill, preflight): they have nothing to stream
but a lifecycle. The screener's genuine SSE activity feed is a per-session
concern that stays in `app/screener/api.py`; the screener joins the matter path
in C2 when the shell needs its stream, at which point this service grows a
streaming sibling — the store-settlement logic below is shared unchanged.

PII rule: everything persisted here (summary_json, log lines) carries ids,
counts, and exception *types* only — never a payload, title, or excerpt. The
Interrupt payload the reviewer must see is the one exception, and it flows to
the firm-visible inbox row, never to a log.
"""
import json
import logging
from typing import Any

from langgraph.types import Command
from pydantic import BaseModel

from app.kernel.config import Settings, get_settings
from app.kernel.package import WorkflowPackage
from app.kernel.runtime.checkpoints import open_sqlite_checkpointer
from app.kernel.runtime.manager import RunManager
from app.kernel.runtime.runner import thread_config
from app.kernel.runtime.scheduler import Scheduler
from app.kernel.store.base import MatterStore, TenantScope
from app.kernel.store.models import Interrupt, WorkflowRun

logger = logging.getLogger("yunaki.kernel.workflows")


class WorkflowError(Exception):
    """A run-lifecycle precondition failed (unknown matter/run/package, or a
    run acted on in the wrong state). The message is a fixed, PII-free string
    the API surfaces in the ApiResponse envelope."""


# Per-package checkpoint DB. Reuses the existing per-package settings fields so
# a run started through the matter path shares the very same parked-thread
# store as the package's own API — a run parked via one path resumes via the
# other. Unknown packages fall back to a generic per-package path.
def _checkpoint_path(package_id: str, settings: Settings) -> str:
    mapping = {
        "autofill": settings.autofill_checkpoint_path,
        "preflight": settings.preflight_checkpoint_path,
        "screener": settings.screener_checkpoint_path,
    }
    return mapping.get(package_id, f"uploads/{package_id}/checkpoints.db")


class WorkflowService:
    def __init__(
        self,
        store: MatterStore,
        packages: tuple[WorkflowPackage, ...],
        *,
        settings: Settings | None = None,
        scheduler: Scheduler | None = None,
    ) -> None:
        """`store` and `packages` are the load-bearing dependencies. `settings`
        and `scheduler` are injectable so tests bind temp checkpoint paths and
        assert scheduling without touching process globals; both default to the
        process settings and a fresh cap-bounded Scheduler."""
        self._store = store
        self._packages: dict[str, WorkflowPackage] = {
            p.manifest.package_id: p for p in packages
        }
        self._settings = settings or get_settings()
        self._scheduler = scheduler or Scheduler(
            self._settings.max_concurrent_runs_per_firm
        )
        self._graphs = RunManager()

    @property
    def scheduler(self) -> Scheduler:
        return self._scheduler

    def package(self, package_id: str) -> WorkflowPackage:
        """The installed package, or raise WorkflowError for an unknown id."""
        package = self._packages.get(package_id)
        if package is None:
            raise WorkflowError("unknown package")
        return package

    async def _graph_for(self, package: WorkflowPackage) -> Any:
        """The package's compiled graph over its own checkpoint DB, built once
        per package and cached (the checkpointer must open exactly once)."""
        package_id = package.manifest.package_id

        async def build() -> Any:
            path = _checkpoint_path(package_id, self._settings)
            checkpointer = await open_sqlite_checkpointer(path)
            graph = package.build_graph(checkpointer=checkpointer)
            logger.info("compiled graph package=%s", package_id)
            return graph

        return await self._graphs.get_or_build(package_id, build)

    # --- Start -------------------------------------------------------------
    async def start_run(
        self,
        scope: TenantScope,
        matter_id: str,
        package_id: str,
        initial_state: BaseModel,
    ) -> WorkflowRun:
        """Open a run against an in-firm matter and drive it to its first
        terminal-or-parked state through the Scheduler. Returns the settled
        WorkflowRun (awaiting_input / done / error)."""
        matter = await self._store.get_matter(scope, matter_id)
        if matter is None:
            raise WorkflowError("matter not found")
        package = self.package(package_id)

        run = await self._store.create_run(scope, matter_id, package_id)
        # The store minted the authoritative run id + thread; re-stamp it onto
        # the state so the graph's own run_id matches the row (thread_id is
        # already firm:matter:run and drives the checkpointer namespace).
        state = _with_run_id(initial_state, run.id)
        graph = await self._graph_for(package)
        config = thread_config(run.thread_id)

        async def execute() -> None:
            await self._store.update_run_status(scope, run.id, "running")
            await self._drive(scope, run, package, graph, config, state)

        task = await self._scheduler.enqueue(scope, run, execute)
        await task
        return await self._refresh(scope, run)

    # --- Resume ------------------------------------------------------------
    async def resume_run(
        self, scope: TenantScope, run_id: str, payload: dict
    ) -> dict:
        """Feed a human-review payload back onto the run's thread and settle
        it. Returns the final state's report dump, or {} when the run produced
        no report (parked again, or completed without one)."""
        run = await self._store.get_run(scope, run_id)
        if run is None:
            raise WorkflowError("run not found")
        if run.status != "awaiting_input":
            raise WorkflowError("run is not awaiting input")
        package = self.package(run.package_id)
        graph = await self._graph_for(package)
        config = thread_config(run.thread_id)

        await self._resolve_pending(scope, run_id)

        report: dict = {}

        async def execute() -> None:
            nonlocal report
            await self._store.update_run_status(scope, run_id, "running")
            result = await self._invoke(
                scope, run, graph, config, Command(resume=payload)
            )
            if result is _FAILED:
                return
            await self._settle(scope, run, package, graph, config, result)
            report = _report_dump(result)

        task = await self._scheduler.enqueue(scope, run, execute)
        await task
        return report

    # --- Reads -------------------------------------------------------------
    async def run_status(
        self, scope: TenantScope, run_id: str
    ) -> WorkflowRun | None:
        """The run row (firm-scoped), or None if not in-firm."""
        return await self._store.get_run(scope, run_id)

    async def pending_interrupts(self, scope: TenantScope) -> list[Interrupt]:
        """The firm's inbox — every pending human-review checkpoint."""
        return await self._store.list_interrupts(scope, status="pending")

    # --- Reconciliation ----------------------------------------------------
    async def reconcile(self, scope: TenantScope | None = None) -> int:
        """Expire orphaned interrupts: for each awaiting_input run in the firm,
        confirm the checkpointer still holds a parked thread; if it does not
        (checkpoint DB wiped, thread never persisted), the run can never be
        resumed, so its pending interrupts are expired and the run is marked
        error. Returns the number of interrupts expired.

        `scope` is required in v1: the tenancy wall exposes no cross-firm
        enumeration, so a firm-less sweep has nothing to iterate — scope=None
        is a no-op the signature keeps for the future admin/all-firms path.

        Called lazily (not on startup) — a single-process desktop app has no
        background sweeper yet; a startup hook can call this later."""
        if scope is None:
            logger.info("reconcile skipped — no firm scope (v1 has no all-firms sweep)")
            return 0
        awaiting = await self._store.list_runs(scope, status="awaiting_input")
        expired = 0
        for run in awaiting:
            package = self._packages.get(run.package_id)
            if package is None:
                continue
            graph = await self._graph_for(package)
            if await _is_parked(graph, run.thread_id):
                continue
            for interrupt in await self._store.list_interrupts(
                scope, status="pending"
            ):
                if interrupt.run_id != run.id:
                    continue
                await self._store.resolve_interrupt(
                    scope, interrupt.id, scope.user_id, status="expired"
                )
                expired += 1
            await self._store.update_run_status(
                scope,
                run.id,
                "error",
                summary_json={"reason": "orphaned_checkpoint"},
                finished_at_now=True,
            )
            logger.info("reconciled orphaned run run_id=%s", run.id)
        return expired

    # --- Internals ---------------------------------------------------------
    async def _drive(
        self,
        scope: TenantScope,
        run: WorkflowRun,
        package: WorkflowPackage,
        graph: Any,
        config: dict,
        input_obj: Any,
    ) -> None:
        result = await self._invoke(scope, run, graph, config, input_obj)
        if result is _FAILED:
            return
        await self._settle(scope, run, package, graph, config, result)

    async def _invoke(
        self,
        scope: TenantScope,
        run: WorkflowRun,
        graph: Any,
        config: dict,
        input_obj: Any,
    ) -> Any:
        """Run the graph, settling any exception into run status. Returns the
        result dict, or the _FAILED sentinel so callers stop."""
        try:
            return await graph.ainvoke(input_obj, config=config)
        except Exception as exc:  # noqa: BLE001 — settle every failure loudly
            logger.exception("run execution failed run_id=%s", run.id)
            await self._store.update_run_status(
                scope,
                run.id,
                "error",
                summary_json={"error_type": type(exc).__name__},
                finished_at_now=True,
            )
            return _FAILED

    async def _settle(
        self,
        scope: TenantScope,
        run: WorkflowRun,
        package: WorkflowPackage,
        graph: Any,
        config: dict,
        result: Any,
    ) -> None:
        """Reflect a graph result into the store: park (Interrupt +
        awaiting_input) if it hit a human gate, else finish (done + report
        artifact)."""
        interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
        if interrupts:
            node = await _parked_node(graph, config)
            kind = (
                package.manifest.interrupt_kinds[0]
                if package.manifest.interrupt_kinds
                else "review"
            )
            payload = interrupts[0].value or {}
            await self._store.create_interrupt(scope, run.id, kind, node, payload)
            await self._store.update_run_status(
                scope, run.id, "awaiting_input", summary_json={"parked_node": node}
            )
            logger.info("run parked run_id=%s node=%s", run.id, node)
            return

        report = _report_dump(result)
        await self._store.update_run_status(
            scope,
            run.id,
            "done",
            summary_json={"has_report": bool(report)},
            finished_at_now=True,
        )
        if report:
            await self._store.add_artifact(
                scope, run.id, "report", json.dumps(report, default=str)
            )
        logger.info("run done run_id=%s has_report=%s", run.id, bool(report))

    async def _resolve_pending(self, scope: TenantScope, run_id: str) -> None:
        """Close every pending interrupt for a run as the reviewer resolves it
        (the resume payload IS the resolution)."""
        for interrupt in await self._store.list_interrupts(scope, status="pending"):
            if interrupt.run_id == run_id:
                await self._store.resolve_interrupt(
                    scope, interrupt.id, scope.user_id, status="resolved"
                )

    async def _refresh(self, scope: TenantScope, run: WorkflowRun) -> WorkflowRun:
        refreshed = await self._store.get_run(scope, run.id)
        return refreshed if refreshed is not None else run


# Sentinel: an invocation that failed and was already settled to error status.
_FAILED: Any = object()


def _with_run_id(state: BaseModel, run_id: str) -> BaseModel:
    """Immutably re-stamp the authoritative run id onto a package state model
    (a new object — never a mutation). No-op when the model has no run_id
    field."""
    if "run_id" in type(state).model_fields:
        return state.model_copy(update={"run_id": run_id})
    return state


def _report_dump(result: Any) -> dict:
    """The `report` field of a graph result as a plain dict (empty when
    absent). Handles both a Pydantic model and an already-dumped dict."""
    if not isinstance(result, dict):
        return {}
    report = result.get("report")
    if report is None:
        return {}
    if isinstance(report, BaseModel):
        return report.model_dump()
    return report if isinstance(report, dict) else {}


async def _parked_node(graph: Any, config: dict) -> str:
    """The graph node the run is parked on (the interrupt's node), read from
    the checkpoint snapshot's next-to-run set."""
    snapshot = await graph.aget_state(config)
    nxt = getattr(snapshot, "next", None) if snapshot is not None else None
    return nxt[0] if nxt else ""


async def _is_parked(graph: Any, thread_id: str) -> bool:
    """True when the checkpointer still holds a resumable parked thread for
    this run (a persisted state with a pending next node)."""
    snapshot = await graph.aget_state(thread_config(thread_id))
    if snapshot is None or not getattr(snapshot, "values", None):
        return False
    return bool(getattr(snapshot, "next", None))
