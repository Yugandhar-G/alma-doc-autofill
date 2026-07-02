"""Validation runner: 20 generated G-28 samples → live extraction → scoring →
offline population → report.

Per sample:
1. extract_document() (live Gemini) → envelope
2. field-level diff vs the persona's ground truth:
   match / WRONG (both non-null, differ) / MISSED (expected value, got null)
   / FABRICATED (expected null, got value — the worst class)
3. populate_form() against the committed form snapshot (offline) with the
   extracted data; population mismatches/errors counted from the report
4. aggregate → docs/validation-report.md

Usage: .venv/bin/python -m validation.run_validation [--limit N]
Requires GEMINI_API_KEY in backend/.env. ~20 flash calls per full run.
"""
import argparse
import asyncio
import sys
import time
from collections import Counter
from pathlib import Path

from app.extraction import extract_document
from app.population import populate_form
from app.schemas import G28Data
from validation.personas import LENIENT_FIELDS, PERSONAS, expected_for

GENERATED = Path(__file__).parent / "generated"
SNAPSHOT = Path(__file__).parent.parent / "tests" / "data" / "form_snapshot.html"
REPORT = Path(__file__).parent.parent.parent / "docs" / "validation-report.md"

# All samples run concurrently; these bound the two resource-heavy stages
# independently (API connections vs Chromium instances).
_EXTRACT_CONCURRENCY = 10
_POPULATE_CONCURRENCY = 5
_EXTRACT_RETRIES = 2  # transient network errors (httpx.ReadError) must not kill a run


def flatten(data: dict) -> dict[str, object]:
    out: dict[str, object] = {}
    for section, fields in data.items():
        for key, value in fields.items():
            out[f"{section}.{key}"] = value
    return out


def classify(expected: object, actual: object) -> str:
    if expected == actual:
        return "match"
    if expected is None and actual is not None:
        return "fabricated"
    if expected is not None and actual is None:
        return "missed"
    return "wrong"


async def _extract_with_retry(pdf_bytes: bytes, name: str):
    for attempt in range(_EXTRACT_RETRIES + 1):
        try:
            return await extract_document(pdf_bytes, f"{name}.pdf", "g28")
        except Exception:
            if attempt == _EXTRACT_RETRIES:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))


async def run_sample(
    name: str, extract_sem: asyncio.Semaphore, populate_sem: asyncio.Semaphore
) -> dict:
    persona = PERSONAS[name]
    pdf_bytes = (GENERATED / f"{name}.pdf").read_bytes()
    try:
        async with extract_sem:
            envelope = await _extract_with_retry(pdf_bytes, name)
    except Exception as exc:  # a broken sample must not kill the other 19
        return {"name": name, "extract_error": f"{type(exc).__name__} after retries"}

    result: dict = {"name": name, "detected": envelope.document_type_detected}
    if envelope.data is None:
        result["extract_error"] = "no data (detected mismatch or withheld)"
        return result

    actual = flatten(envelope.data)
    expected = expected_for(persona)
    field_results: dict[str, str] = {}
    for path, expected_value in expected.items():
        field_results[path] = classify(expected_value, actual.get(path))
    for path, acceptable in LENIENT_FIELDS.items():
        field_results[path] = "match" if actual.get(path) in acceptable else "wrong"

    result["fields"] = field_results
    result["errors"] = {
        p: (expected.get(p), actual.get(p))
        for p, c in field_results.items()
        if c != "match"
    }

    async with populate_sem:
        report = await populate_form(
            passport=None,
            g28=G28Data.model_validate(envelope.data),
            headed=False,
            target_url=SNAPSHOT.resolve().as_uri(),
        )
    result["populate"] = {
        "filled": report.filled,
        "skipped_null": report.skipped_null,
        "mismatches": report.mismatches,
        "errors": report.errors,
        "ok": report.ok,
    }
    return result


def render_report(results: list[dict]) -> str:
    scored = [r for r in results if "fields" in r]
    total_counter: Counter[str] = Counter()
    per_field_errors: Counter[str] = Counter()
    lines = [
        "# Validation Report — 20 Synthetic G-28 Samples",
        "",
        "Generated variants of the example G-28 (names with diacritics/apostrophes/",
        "hyphens, 15+ states, N/A traps on email and bar number, filled-mobile,",
        "abbreviation normalization) run through live Gemini extraction, scored",
        "field-by-field against known ground truth, then populated into the form",
        "snapshot with post-fill read-back verification.",
        "",
        "| # | Sample | Fields OK | Wrong | Missed | Fabricated | Populate |",
        "|---|--------|-----------|-------|--------|------------|----------|",
    ]
    for r in results:
        if "fields" not in r:
            lines.append(f"| — | {r['name']} | EXTRACT FAILED: {r['extract_error']} | | | | |")
            continue
        c = Counter(r["fields"].values())
        total_counter.update(c)
        for path, klass in r["fields"].items():
            if klass != "match":
                per_field_errors[f"{path} ({klass})"] += 1
        p = r["populate"]
        pop = (
            f"{p['filled']} filled / {p['mismatches']} mm / {p['errors']} err"
            + (" ✓" if p["ok"] else " ✗")
        )
        n_fields = len(r["fields"])
        lines.append(
            f"| {r['name'].split('-')[0]} | {r['name']} | {c['match']}/{n_fields} "
            f"| {c['wrong']} | {c['missed']} | {c['fabricated']} | {pop} |"
        )

    n_docs = len(scored)
    perfect = sum(1 for r in scored if set(r["fields"].values()) == {"match"})
    total_fields = sum(len(r["fields"]) for r in scored)
    pop_ok = sum(1 for r in scored if r["populate"]["ok"])
    lines += [
        "",
        "## Aggregate",
        "",
        f"- **Field accuracy:** {total_counter['match']}/{total_fields} "
        f"({100 * total_counter['match'] / max(1, total_fields):.1f}%)",
        f"- **Document accuracy (all fields correct):** {perfect}/{n_docs}",
        f"- **Fabricated values (expected null, got value):** {total_counter['fabricated']}",
        f"- **Missed values (expected value, got null):** {total_counter['missed']}",
        f"- **Wrong values:** {total_counter['wrong']}",
        f"- **Population runs clean (0 mismatch / 0 error):** {pop_ok}/{n_docs}",
    ]
    if per_field_errors:
        lines += ["", "## Errors by field", ""]
        for field, count in per_field_errors.most_common():
            lines.append(f"- {field}: {count}")
        lines += ["", "## Per-sample error detail", ""]
        for r in scored:
            if r["errors"]:
                lines.append(f"**{r['name']}**")
                for path, (exp, act) in r["errors"].items():
                    lines.append(f"- `{path}`: expected {exp!r}, got {act!r}")
                lines.append("")
    else:
        lines += ["", "No field errors across any sample."]
    return "\n".join(lines) + "\n"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="run first N samples")
    args = parser.parse_args()

    names = list(PERSONAS)[: args.limit]
    missing = [n for n in names if not (GENERATED / f"{n}.pdf").exists()]
    if missing:
        print(f"missing samples {missing}; run generate_samples first", file=sys.stderr)
        return 1

    started = time.monotonic()
    extract_sem = asyncio.Semaphore(_EXTRACT_CONCURRENCY)
    populate_sem = asyncio.Semaphore(_POPULATE_CONCURRENCY)
    results = await asyncio.gather(
        *(run_sample(n, extract_sem, populate_sem) for n in names)
    )
    elapsed = time.monotonic() - started
    print(f"{len(names)} samples in {elapsed:.1f}s "
          f"(extract x{_EXTRACT_CONCURRENCY}, populate x{_POPULATE_CONCURRENCY})\n")
    report = render_report(list(results))
    REPORT.write_text(report, encoding="utf-8")
    print(report)
    print(f"report written to {REPORT}")
    scored = [r for r in results if "fields" in r]
    all_clean = all(
        set(r["fields"].values()) == {"match"} and r["populate"]["ok"] for r in scored
    ) and len(scored) == len(results)
    return 0 if all_clean else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
