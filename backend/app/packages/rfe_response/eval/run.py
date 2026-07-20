"""Offline RFE-response eval loop — a thin config over app.kernel.evalkit.Harness.

Fully offline (no LLM, no network): each persona's synthetic notice + proposed
checklist runs straight through the deterministic path — deadline math, the
citation audit, and the cover assembly — and the run emits a set of behavior
LABELS that are compared against the persona's expected set.

worst_class = "fabricated": a checklist item citing a non-existent ground that
SURVIVES the audit ("survived_fabricated_ground"), or a null deadline that
receives a guessed day-count ("deadline_guessed"), are labels no persona ever
expects — so they land in the fabricated bucket and the harness hard-fails. The
package gate also fails on a "missed" label (the audit failing to drop / warn
what it should).

Usage: cd backend && python -m app.packages.rfe_response.eval.run
"""
import asyncio
import sys
from collections import Counter

from app.kernel.evalkit import HARNESS_ERROR_KEY, Harness
from app.packages.rfe_response.deadlines import CRITICAL_DAYS, WARNING_DAYS, deadline_status
from app.packages.rfe_response.eval.personas import PERSONAS, RfePersona, classify
from app.packages.rfe_response.refs_audit import audit_checklist, build_cover_structure


def _labels(persona: RfePersona) -> set[str]:
    """The deterministic behavior labels one persona's run produces."""
    notice = persona.notice
    ground_ids = [ground.ground_id for ground in notice.grounds]
    valid_grounds = set(ground_ids)
    days, _ = deadline_status(notice.response_deadline, persona.today)
    kept, warnings = audit_checklist(persona.raw_items, ground_ids, persona.matter_doc_ids)
    build_cover_structure(notice.grounds, kept)  # exercised; assertions live in unit tests

    labels: set[str] = set()
    dropped = any("fabricated ground" in w for w in warnings)
    stripped = any("invented ref" in w for w in warnings)
    if dropped:
        labels.add("dropped_fabricated_ground")
    if stripped:
        labels.add("stripped_ref")
    # Defect: an item citing a non-existent ground that the audit let survive.
    if any(item.ground_id not in valid_grounds for item in kept):
        labels.add("survived_fabricated_ground")
    covered = {item.ground_id for item in kept}
    if all(g in covered for g in ground_ids) and not dropped and not stripped:
        labels.add("clean_map")

    # Deadline honesty.
    if notice.response_deadline is None:
        labels.add("deadline_unverifiable")
        if days is not None:  # defect: guessed a day-count with no date
            labels.add("deadline_guessed")
    elif days is None:
        labels.add("deadline_unverifiable")  # present but unparseable
    elif days < CRITICAL_DAYS:
        labels.add("deadline_critical")
    elif days < WARNING_DAYS:
        labels.add("deadline_warning")
    return labels


async def run_persona(persona: RfePersona) -> dict:
    actual = _labels(persona)
    buckets = classify(persona.expected, frozenset(actual))
    return {
        "persona": persona.name,
        "expected": sorted(persona.expected),
        "actual": sorted(actual),
        "buckets": buckets,
    }


def classes_of(result: dict) -> set[str]:
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
        "# RFE-Response Eval Report",
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
    """Fail on any fabricated label OR any missed expected label."""
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
    harness = build_harness()
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
