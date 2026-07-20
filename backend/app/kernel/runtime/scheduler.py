"""In-process workflow executor for the desktop model.

Runs execute on the machine that starts them (CLAUDE.md desktop thesis); there
is no cron, no polling, no broker. `enqueue` creates an asyncio task the moment
it is called; the task blocks on a per-firm semaphore and executes as soon as a
slot is free. The durable queue record is the WorkflowRun row itself (status
"queued" → "running"), not anything the Scheduler holds — the Scheduler owns
only the live task set and the concurrency gate.

The interface is deliberately tiny (enqueue / shutdown) so a worker-process or
Redis-backed executor can replace this class later without any API-layer
change: `enqueue` returns an awaitable that resolves when the run reaches a
terminal-or-parked state, which is all a caller (WorkflowService) depends on.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.kernel.store.base import TenantScope
from app.kernel.store.models import WorkflowRun

logger = logging.getLogger("yunaki.kernel.scheduler")

Work = Callable[[], Awaitable[None]]


class Scheduler:
    """Per-firm-capped asyncio executor. One `asyncio.Semaphore` per firm,
    each sized to `max_concurrent_per_firm`, so one firm saturating its slots
    never starves another. Single-process by design (the event loop is the
    only worker); the semaphore, not a thread pool, is the ceiling."""

    def __init__(self, max_concurrent_per_firm: int) -> None:
        if max_concurrent_per_firm < 1:
            raise ValueError("max_concurrent_per_firm must be >= 1")
        self._cap = max_concurrent_per_firm
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._tasks: set[asyncio.Task] = set()
        self._shutting_down = False

    def _semaphore(self, firm_id: str) -> asyncio.Semaphore:
        """The firm's admission gate, created on first use. Access is safe
        without a lock: the event loop is single-threaded, so this dict is
        never mutated concurrently mid-await."""
        sem = self._semaphores.get(firm_id)
        if sem is None:
            sem = asyncio.Semaphore(self._cap)
            self._semaphores[firm_id] = sem
        return sem

    async def enqueue(
        self, scope: TenantScope, run: WorkflowRun, execute: Work
    ) -> asyncio.Task:
        """Schedule `execute` under the firm's concurrency cap. Returns the
        task immediately; the caller awaits it to observe the run reaching a
        terminal-or-parked state. The task exists the instant this returns but
        does not begin `execute` until the semaphore admits it."""
        if self._shutting_down:
            raise RuntimeError("scheduler is shutting down")
        sem = self._semaphore(scope.firm_id)
        task = asyncio.create_task(
            self._guarded(sem, execute, run.id, scope.firm_id)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _guarded(
        self, sem: asyncio.Semaphore, execute: Work, run_id: str, firm_id: str
    ) -> None:
        """Acquire the firm slot, run the work, always release. `execute` owns
        its own error handling (WorkflowService settles failures into run
        status); anything that still escapes is logged by id only — never a
        payload — and re-raised so the awaiting caller sees it."""
        async with sem:
            logger.info("run admitted run_id=%s firm_id=%s", run_id, firm_id)
            await execute()

    async def shutdown(self) -> None:
        """Cancel every in-flight task and wait for them to unwind. Idempotent;
        after it returns, `enqueue` refuses new work."""
        self._shutting_down = True
        pending = list(self._tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        logger.info("scheduler shutdown cancelled=%d", len(pending))
