"""Offline tests for the kernel eval harness (app.kernel.evalkit).

No live calls, no fixtures: fake personas, a fake run_one. Covers the three
kernel-owned behaviors the validation runners depend on: bounded-concurrent
execution with per-item isolation, the worst-class exit gate (kernel-enforced,
not opt-in), and clean-run exit 0. Plus the shared retry helper.
"""
import asyncio

import pytest

from app.kernel.evalkit import HARNESS_ERROR_KEY, Harness, retry_async


def make_harness(**overrides) -> Harness:
    """A minimal harness over string personas; run_one classifies via a
    'classes' set embedded in the result (how both real runners surface
    classification to the kernel)."""

    async def run_one(persona: str) -> dict:
        await asyncio.sleep(0.01)
        if persona.startswith("boom"):
            raise RuntimeError("synthetic failure")
        if persona.startswith("worst"):
            return {"name": persona, "classes": {"correct", "overclaim"}}
        return {"name": persona, "classes": {"correct"}}

    defaults = dict(
        personas=["p1", "p2", "p3"],
        run_one=run_one,
        classes_of=lambda r: r.get("classes", set()),
        render=lambda results: f"{len(results)} results",
        gate=lambda results: 0,
        worst_class="overclaim",
        concurrency=2,
        error_result=lambda persona, exc: {"name": persona, "classes": set()},
    )
    return Harness(**{**defaults, **overrides})


async def test_runs_concurrently_and_isolates_raising_persona():
    """One raising persona becomes an error result in order; the other
    personas still complete, and the run stays bounded by the semaphore."""
    in_flight = 0
    max_in_flight = 0

    async def run_one(persona: str) -> dict:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        try:
            await asyncio.sleep(0.02)
            if persona == "boom":
                raise ValueError("synthetic failure")
            return {"name": persona, "classes": {"correct"}}
        finally:
            in_flight -= 1

    harness = make_harness(
        personas=["a", "boom", "c", "d"], run_one=run_one, concurrency=2
    )
    results = await harness.run()

    assert [r["name"] for r in results] == ["a", "boom", "c", "d"]
    assert HARNESS_ERROR_KEY not in results[0]
    assert results[1][HARNESS_ERROR_KEY] == "ValueError"
    assert HARNESS_ERROR_KEY not in results[2]
    assert 2 <= max_in_flight <= 2  # bounded by the semaphore, actually parallel


async def test_error_result_forces_nonzero_exit_even_when_gate_passes():
    harness = make_harness(personas=["p1", "boom-1"], gate=lambda results: 0)
    results = await harness.run()
    assert harness.exit_code(results) != 0


async def test_worst_class_forces_nonzero_exit_even_when_gate_passes():
    """The kernel-owned overclaim gate: the package gate says 0, but a result
    classified with the declared worst class must still fail the run."""
    harness = make_harness(personas=["p1", "worst-1"], gate=lambda results: 0)
    results = await harness.run()
    assert all(HARNESS_ERROR_KEY not in r for r in results)
    assert harness.exit_code(results) != 0


async def test_worst_class_uses_declared_defect_exit_code():
    harness = make_harness(
        personas=["worst-1"], gate=lambda results: 0, defect_exit_code=2
    )
    results = await harness.run()
    assert harness.exit_code(results) == 2


async def test_package_gate_verdict_wins_when_nonzero():
    harness = make_harness(personas=["p1"], gate=lambda results: 2)
    results = await harness.run()
    assert harness.exit_code(results) == 2


async def test_clean_results_exit_zero():
    harness = make_harness(personas=["p1", "p2", "p3"])
    results = await harness.run()
    assert all(HARNESS_ERROR_KEY not in r for r in results)
    assert harness.exit_code(results) == 0
    assert harness.render(results) == "3 results"


async def test_unbounded_concurrency_allowed():
    """concurrency=None → no outer semaphore (the extraction runner bounds
    per-stage inside run_one instead)."""
    harness = make_harness(personas=["p1", "p2"], concurrency=None)
    results = await harness.run()
    assert harness.exit_code(results) == 0


def test_zero_defect_exit_code_rejected():
    with pytest.raises(ValueError):
        make_harness(defect_exit_code=0)


async def test_before_and_after_item_hooks():
    seen: list[str] = []
    harness = make_harness(
        personas=["p1", "boom-1"],
        before_item=lambda p: seen.append(f"start:{p}"),
        after_item=lambda p, r: seen.append(f"done:{p}"),
    )
    await harness.run()
    assert "start:p1" in seen and "done:p1" in seen
    assert "start:boom-1" in seen
    assert "done:boom-1" not in seen  # after_item only fires on success


async def test_retry_async_recovers_from_transient_failures():
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("transient")
        return "ok"

    assert await retry_async(flaky, retries=2, base_delay=0) == "ok"
    assert attempts == 3


async def test_retry_async_reraises_after_exhaustion():
    attempts = 0

    async def broken() -> None:
        nonlocal attempts
        attempts += 1
        raise ConnectionError("permanent")

    with pytest.raises(ConnectionError):
        await retry_async(broken, retries=2, base_delay=0)
    assert attempts == 3
