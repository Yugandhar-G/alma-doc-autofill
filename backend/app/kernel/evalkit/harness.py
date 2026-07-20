"""Shared eval harness — the kernel's one way to run a persona-based eval.

Both validation runners (extraction/population and screener) were ~70% the
same shape with zero shared code: asyncio.gather over personas, bounded
semaphores, per-item exception isolation, Counter totals, a markdown report,
and a defect-gated exit code. The Harness owns that shape; the package
supplies the parts that differ — personas, an async ``run_one``, its own
classification logic (surfaced to the kernel via ``classes_of``), a markdown
``render``, and a ``gate`` exit-code predicate.

Kernel-owned invariant (not opt-in): every package declares a
``worst_class`` — its unforgivable defect class ("fabricated" for
extraction, "overclaim" for the screener). Any result whose classification
set contains that class forces a nonzero exit even when the package's own
gate would return 0. A run that isolated an exception into an error result
is likewise never allowed to exit 0.

PII rule: the harness logs exception *types* only, never messages — eval
inputs are synthetic today, but kernel code must not assume that.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Sequence, TypeVar

logger = logging.getLogger("yunaki.evalkit")

# Reserved result key marking a persona whose run_one raised and was isolated
# into an error result instead of killing the run. Value: exception type name.
HARNESS_ERROR_KEY = "harness_error"

T = TypeVar("T")

Result = dict[str, Any]


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    retries: int = 2,
    base_delay: float = 1.5,
) -> T:
    """Retry a zero-arg async callable with linear backoff.

    Sleeps ``base_delay * attempt_number`` between attempts (1.5s, 3.0s, ...
    with the defaults) — transient network errors (httpx.ReadError) must not
    kill an eval run. The final failure re-raises the original exception.
    """
    for attempt in range(retries + 1):
        try:
            return await fn()
        except Exception:
            if attempt == retries:
                raise
            await asyncio.sleep(base_delay * (attempt + 1))
    raise RuntimeError("unreachable")  # pragma: no cover


@dataclass(frozen=True)
class Harness:
    """One persona-based eval run: concurrency, isolation, and the exit gate.

    The harness never prints and never writes files — rendering output and
    report paths stay in the runner scripts so their CLI contracts stay
    frozen. It also never classifies: ``classes_of`` only *extracts* the
    package's already-computed classification labels from a result so the
    kernel can enforce the worst-class gate.
    """

    personas: Sequence[Any]
    run_one: Callable[[Any], Awaitable[Result]]
    classes_of: Callable[[Result], Iterable[str]]
    render: Callable[[list[Result]], str]
    gate: Callable[[list[Result]], int]
    worst_class: str
    # None → unbounded outer gather (a package may bound per-stage inside
    # run_one instead, as the extraction runner does with its dual semaphores).
    concurrency: int | None = None
    # Exit code forced by the kernel when the worst class (or an isolated
    # error) appears but the package gate returned 0. Must be nonzero.
    defect_exit_code: int = 1
    # Builds the package-shaped skeleton of an error result so the package's
    # render can display it; the kernel stamps HARNESS_ERROR_KEY on top.
    error_result: Callable[[Any, Exception], Result] | None = None
    # Progress hooks, called inside the semaphore (matches the previous
    # inline ``guarded`` wrappers). after_item runs only on success.
    before_item: Callable[[Any], None] | None = None
    after_item: Callable[[Any, Result], None] | None = None

    def __post_init__(self) -> None:
        if self.defect_exit_code == 0:
            raise ValueError("defect_exit_code must be nonzero")
        if self.concurrency is not None and self.concurrency < 1:
            raise ValueError("concurrency must be >= 1 (or None for unbounded)")

    async def run(self) -> list[Result]:
        """All personas concurrently (bounded if ``concurrency`` is set);
        one raising persona becomes an error result, never a dead run.
        Results come back in persona order."""
        semaphore = (
            asyncio.Semaphore(self.concurrency) if self.concurrency is not None else None
        )

        async def one(persona: Any) -> Result:
            try:
                if semaphore is None:
                    return await self._run_item(persona)
                async with semaphore:
                    return await self._run_item(persona)
            except Exception as exc:  # isolation: log the shape, keep the run alive
                logger.error(
                    "eval persona run failed: %s (isolated into error result)",
                    type(exc).__name__,
                )
                base = self.error_result(persona, exc) if self.error_result else {}
                return {**base, HARNESS_ERROR_KEY: type(exc).__name__}

        return list(await asyncio.gather(*(one(p) for p in self.personas)))

    async def _run_item(self, persona: Any) -> Result:
        if self.before_item is not None:
            self.before_item(persona)
        result = await self.run_one(persona)
        if self.after_item is not None:
            self.after_item(persona, result)
        return result

    def exit_code(self, results: Sequence[Result]) -> int:
        """The package gate decides first; the kernel then enforces its two
        hard bars — worst-class presence and isolated errors never exit 0."""
        code = self.gate(list(results))
        if code != 0:
            return code
        has_worst = any(self.worst_class in set(self.classes_of(r)) for r in results)
        has_error = any(HARNESS_ERROR_KEY in r for r in results)
        if has_worst or has_error:
            return self.defect_exit_code
        return 0
