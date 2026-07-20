"""Offline preflight eval loop — a thin config over app.kernel.evalkit.Harness.

Fully offline (no LLM, no network): each persona is a synthetic packet run
straight through the deterministic battery, so this runs in CI. The kernel owns
concurrency, per-persona isolation, and the hard exit bar; this module owns the
packet run, the classification, and the markdown render.

worst_class = "fabricated": a check that fires on a packet it should not is the
unforgivable defect (a clean packet MUST stay clean). The package gate also
fails on a "missed" planted defect — an audit that misses the thing it was
built to catch is a failure too, just not the fabrication class.

Usage: cd backend && python -m app.packages.preflight.eval.run
"""
import asyncio
import sys
from collections import Counter
from contextlib import contextmanager
from unittest.mock import patch

from app.kernel.evalkit import HARNESS_ERROR_KEY, Harness
from app.packages.preflight.checks import run_checks
from app.packages.preflight.eval.personas import (
    PERSONAS,
    SYNTHETIC_REGISTRY,
    PreflightPersona,
    classify,
)
from app.packages.preflight.knowledge import form_editions
from app.packages.preflight.packet import gather_packet


@contextmanager
def synthetic_editions():
    """Install the synthetic form-edition registry for the duration of the eval
    (production is intentionally empty). Honest: the eval exercises the edition
    check against clearly-synthetic data, never a fabricated production entry."""
    with patch.object(form_editions, "_REGISTRY", SYNTHETIC_REGISTRY):
        yield


async def run_persona(persona: PreflightPersona) -> dict:
    packet = gather_packet(
        list(persona.envelopes), persona.case_type, dict(persona.declared_editions)
    )
    findings = run_checks(packet)
    actual = frozenset(f.check_id for f in findings)
    buckets = classify(persona.expected, actual)
    return {
        "persona": persona.name,
        "expected": sorted(persona.expected),
        "actual": sorted(actual),
        "buckets": buckets,
        "findings": len(findings),
    }


def classes_of(result: dict) -> set[str]:
    """The classification labels present in one persona result — the kernel's
    worst-class gate reads these. A label is 'present' when its bucket is
    non-empty."""
    buckets = result.get("buckets", {})
    return {name for name, ids in buckets.items() if ids}


def collect_totals(results: list[dict]) -> Counter:
    totals: Counter = Counter()
    for result in results:
        for name, ids in result.get("buckets", {}).items():
            totals[name] += len(ids)
    return totals


def render_report(results: list[dict]) -> str:
    totals = collect_totals(results)
    lines = [
        "# Preflight Eval Report",
        "",
        f"{len(results)} synthetic personas · offline · no LLM.",
        "Classes: correct · **fabricated (defect — hard fail)** · missed.",
        "",
        "| persona | expected | actual | correct | fabricated | missed |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        if HARNESS_ERROR_KEY in result:
            lines.append(
                f"| {result.get('persona','?')} | — | — | — | "
                f"**RUN FAILED: {result[HARNESS_ERROR_KEY]}** | — |"
            )
            continue
        buckets = result["buckets"]
        fab = ", ".join(buckets["fabricated"]) or "-"
        flag = " ⚠️" if buckets["fabricated"] else ""
        lines.append(
            f"| {result['persona']} | {', '.join(result['expected']) or '-'} "
            f"| {', '.join(result['actual']) or '-'} "
            f"| {', '.join(buckets['correct']) or '-'} | {fab}{flag} "
            f"| {', '.join(buckets['missed']) or '-'} |"
        )
    lines.extend(
        [
            "",
            "## Totals",
            "",
            f"- correct: {totals['correct']}",
            f"- **fabricated: {totals['fabricated']}**",
            f"- missed: {totals['missed']}",
        ]
    )
    return "\n".join(lines) + "\n"


def gate(results: list[dict]) -> int:
    """Fail on any fabricated finding OR any missed planted defect."""
    totals = collect_totals(results)
    return 1 if (totals["fabricated"] or totals["missed"]) else 0


def build_harness() -> Harness:
    return Harness(
        personas=PERSONAS,
        run_one=run_persona,
        classes_of=classes_of,
        render=render_report,
        gate=gate,
        worst_class="fabricated",
        error_result=lambda persona, exc: {
            "persona": persona.name,
            "buckets": {"correct": [], "fabricated": [], "missed": []},
        },
    )


async def evaluate() -> tuple[list[dict], int, str]:
    """Run the eval and return (results, exit_code, rendered_report). The
    synthetic edition registry is installed only for the duration of the run."""
    harness = build_harness()
    with synthetic_editions():
        results = await harness.run()
    return results, harness.exit_code(results), harness.render(results)


async def main() -> int:
    results, code, text = await evaluate()
    print(text)
    totals = collect_totals(results)
    print(
        f"correct={totals['correct']} FABRICATED={totals['fabricated']} "
        f"missed={totals['missed']} → exit {code}"
    )
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
