"""Screener eval loop: run every persona through the live graph (web
enrichment forced OFF for determinism), auto-resume the review interrupt with
the unedited matrix, score per-criterion verdicts and per-visa
recommendations, and write docs/screener-validation-report.md.

Exit code 0 only when there are ZERO overclaims — the harness's hard bar.
Underclaims/lenient are reported but do not fail the run (a conservative
screener is acceptable; an optimistic one is not).

Thin config over app.kernel.evalkit.Harness: this module owns the graph
invocation, banded classification, and report rendering; the kernel owns
concurrency, per-persona isolation, and the overclaim-is-never-exit-0 gate.

Usage: cd backend && python -m validation.run_screener_validation
Requires GEMINI_API_KEY (live calls, ~2 LLM calls + criteria-count per persona).
"""
import asyncio
import os
import sys
import time
from collections import Counter
from pathlib import Path

# Determinism: enrichment off for the harness regardless of .env. Must be set
# before the Settings singleton is first constructed.
os.environ["SCREENER_WEB_ENRICHMENT"] = "false"

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import get_settings
from app.kernel.evalkit import HARNESS_ERROR_KEY, Harness
from app.screener.criteria import criteria_for_targets
from app.screener.graph import build_graph
from app.screener.state import ScreenerState
from validation.screener_personas import (
    PERSONAS,
    RECOMMENDATION_RANK,
    ScreenerPersona,
    classify,
    expected_for,
)

REPORT_PATH = Path(__file__).resolve().parents[2] / "docs" / "screener-validation-report.md"
CONCURRENCY = 3  # personas in flight (each fans out ~10 assess calls internally)


async def run_persona(persona: ScreenerPersona, graph) -> dict:
    config = {"configurable": {"thread_id": f"validation-{persona.name}"}}
    state = ScreenerState(
        session_id=f"validation-{persona.name}",
        visa_targets=list(persona.visa_targets),
        intake=persona.intake,
        evidence_docs=list(persona.evidence_docs),
    )
    started = time.monotonic()
    first = await graph.ainvoke(state, config=config)
    matrix = first["__interrupt__"][0].value["matrix"]
    final = await graph.ainvoke(Command(resume=matrix), config=config)
    report = final["report"]

    rows = []
    for spec in criteria_for_targets(list(persona.visa_targets)):
        actual = next(
            (a.verdict for a in report.assessments if a.criterion_id == spec.id),
            "not_met",
        )
        expected = expected_for(persona, spec.id)
        rows.append(
            {
                "criterion": spec.id,
                "expected": "/".join(sorted(expected)),
                "actual": actual,
                "class": classify(expected, actual),
            }
        )

    rec_rows = []
    for visa, acceptable in persona.expected_recommendation.items():
        actual_rec = next(
            (v.recommendation for v in report.verdicts if v.visa == visa), "missing"
        )
        if actual_rec in acceptable:
            rec_class = "correct"
        elif actual_rec == "missing":
            rec_class = "missing"
        else:
            ceiling = max(RECOMMENDATION_RANK[r] for r in acceptable)
            rec_class = (
                "overclaim" if RECOMMENDATION_RANK[actual_rec] > ceiling else "underclaim"
            )
        rec_rows.append(
            {
                "visa": visa,
                "expected": "/".join(sorted(acceptable)),
                "actual": actual_rec,
                "class": rec_class,
            }
        )

    return {
        "persona": persona.name,
        "criteria": rows,
        "recommendations": rec_rows,
        "warnings": len(report.warnings),
        "seconds": round(time.monotonic() - started, 1),
    }


def collect_totals(results: list[dict]) -> Counter:
    """Class totals across all personas: criterion classes by name,
    recommendation classes prefixed rec_."""
    totals: Counter = Counter()
    for result in results:
        for row in result.get("criteria", ()):
            totals[row["class"]] += 1
        for rec in result.get("recommendations", ()):
            totals[f"rec_{rec['class']}"] += 1
    return totals


def classes_of(result: dict) -> set[str]:
    """Every classification label in one persona result (criteria and
    recommendations alike) — the kernel's overclaim gate reads these."""
    return {row["class"] for row in result.get("criteria", ())} | {
        rec["class"] for rec in result.get("recommendations", ())
    }


def render_report(results: list[dict]) -> str:
    totals = collect_totals(results)
    lines = [
        "# Screener Validation Report",
        "",
        f"{len(results)} personas · web enrichment off · unedited-matrix auto-resume.",
        "Classes: correct · lenient (one band conservative) · underclaim · "
        "**overclaim (defect — hard fail)**.",
        "",
    ]
    for result in results:
        lines.append(f"## {result['persona']}  ({result['seconds']}s, "
                     f"{result['warnings']} warnings)")
        lines.append("")
        if HARNESS_ERROR_KEY in result:
            # Previously a raising persona killed the whole run; the kernel
            # now isolates it — surfaced here and forced nonzero at exit.
            lines.append(f"**RUN FAILED**: {result[HARNESS_ERROR_KEY]}")
            lines.append("")
            continue
        lines.append("| criterion | expected | actual | class |")
        lines.append("|---|---|---|---|")
        for row in result["criteria"]:
            flag = " ⚠️" if row["class"] == "overclaim" else ""
            lines.append(
                f"| {row['criterion']} | {row['expected']} | {row['actual']} "
                f"| {row['class']}{flag} |"
            )
        lines.append("")
        for rec in result["recommendations"]:
            flag = " ⚠️" if rec["class"] == "overclaim" else ""
            lines.append(
                f"- **{rec['visa']} recommendation**: expected {rec['expected']}, "
                f"got `{rec['actual']}` → {rec['class']}{flag}"
            )
        lines.append("")

    graded = sum(totals[c] for c in ("correct", "lenient", "underclaim", "overclaim"))
    lines.append("## Totals")
    lines.append("")
    lines.append(
        f"- Criteria: {totals['correct']}/{graded} correct, "
        f"{totals['lenient']} lenient, {totals['underclaim']} underclaim, "
        f"**{totals['overclaim']} overclaim**"
    )
    lines.append(
        f"- Recommendations: {totals['rec_correct']} correct, "
        f"{totals['rec_underclaim']} underclaim, "
        f"**{totals['rec_overclaim']} overclaim**, {totals['rec_missing']} missing"
    )
    return "\n".join(lines) + "\n"


def gate(results: list[dict]) -> int:
    totals = collect_totals(results)
    return 1 if totals["overclaim"] + totals["rec_overclaim"] else 0


def build_harness(graph) -> Harness:
    return Harness(
        personas=PERSONAS,
        run_one=lambda persona: run_persona(persona, graph),
        classes_of=classes_of,
        render=render_report,
        gate=gate,
        worst_class="overclaim",
        concurrency=CONCURRENCY,
        error_result=lambda persona, exc: {
            "persona": persona.name,
            "criteria": [],
            "recommendations": [],
            "warnings": 0,
            "seconds": 0.0,
        },
        before_item=lambda persona: print(f"→ {persona.name}"),
        after_item=lambda persona, result: print(
            f"✓ {persona.name} ({result['seconds']}s)"
        ),
    )


async def main() -> int:
    settings = get_settings()
    settings.require_gemini_key()
    assert settings.screener_web_enrichment is False  # env guard above worked

    graph = build_graph(checkpointer=MemorySaver())
    harness = build_harness(graph)
    results = await harness.run()
    text = harness.render(list(results))
    REPORT_PATH.write_text(text)
    print(f"\nreport → {REPORT_PATH}")
    totals = collect_totals(list(results))
    overclaims = totals["overclaim"] + totals["rec_overclaim"]
    print(
        f"criteria correct={totals['correct']} lenient={totals['lenient']} "
        f"underclaim={totals['underclaim']} OVERCLAIM={overclaims}"
    )
    return harness.exit_code(results)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
