"""Screener eval loop: run every persona through the live graph (web
enrichment forced OFF for determinism), auto-resume the review interrupt with
the unedited matrix, score per-criterion verdicts and per-visa
recommendations, and write docs/screener-validation-report.md.

Exit code 0 only when there are ZERO overclaims — the harness's hard bar.
Underclaims/lenient are reported but do not fail the run (a conservative
screener is acceptable; an optimistic one is not).

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


def render_report(results: list[dict]) -> tuple[str, Counter]:
    totals: Counter = Counter()
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
        lines.append("| criterion | expected | actual | class |")
        lines.append("|---|---|---|---|")
        for row in result["criteria"]:
            totals[row["class"]] += 1
            flag = " ⚠️" if row["class"] == "overclaim" else ""
            lines.append(
                f"| {row['criterion']} | {row['expected']} | {row['actual']} "
                f"| {row['class']}{flag} |"
            )
        lines.append("")
        for rec in result["recommendations"]:
            totals[f"rec_{rec['class']}"] += 1
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
    return "\n".join(lines) + "\n", totals


async def main() -> int:
    settings = get_settings()
    settings.require_gemini_key()
    assert settings.screener_web_enrichment is False  # env guard above worked

    graph = build_graph(checkpointer=MemorySaver())
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def guarded(persona: ScreenerPersona) -> dict:
        async with semaphore:
            print(f"→ {persona.name}")
            result = await run_persona(persona, graph)
            print(f"✓ {persona.name} ({result['seconds']}s)")
            return result

    results = await asyncio.gather(*(guarded(p) for p in PERSONAS))
    text, totals = render_report(list(results))
    REPORT_PATH.write_text(text)
    print(f"\nreport → {REPORT_PATH}")
    overclaims = totals["overclaim"] + totals["rec_overclaim"]
    print(
        f"criteria correct={totals['correct']} lenient={totals['lenient']} "
        f"underclaim={totals['underclaim']} OVERCLAIM={overclaims}"
    )
    return 1 if overclaims else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
