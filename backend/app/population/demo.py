"""CLI demo for the population plane.

    python -m app.population.demo path/to/data.json [--headless]

The JSON file is shaped ``{"passport": {...}, "g28": {...}}`` (either key
may be null or absent). Values are validated through the same Pydantic
schemas the extraction plane uses, then populate_form runs against the
real target URL and the PopulationReport is printed as a table.

No sample data is embedded here by design (project rule: no hardcoding) —
point it at a JSON dump of extracted/reviewed data.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from app.population.fill import populate_form
from app.schemas import G28Data, PassportData, PopulationReport

USAGE = "python -m app.population.demo path/to/data.json [--headless]"


def _load_documents(path: Path) -> tuple[PassportData | None, G28Data | None]:
    """Parse and schema-validate the input JSON. Raises loudly on bad input."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("input JSON must be an object with 'passport' and/or 'g28' keys")
    passport_raw = payload.get("passport")
    g28_raw = payload.get("g28")
    passport = PassportData.model_validate(passport_raw) if passport_raw is not None else None
    g28 = G28Data.model_validate(g28_raw) if g28_raw is not None else None
    if passport is None and g28 is None:
        raise ValueError("input JSON contains neither 'passport' nor 'g28' data")
    return passport, g28


def _print_report(report: PopulationReport) -> None:
    headers = ("selector", "action", "status", "expected", "actual")
    rows = [
        (
            entry.selector,
            entry.action,
            entry.status,
            entry.expected if entry.expected is not None else "-",
            entry.actual if entry.actual is not None else "-",
        )
        for entry in report.entries
    ]
    widths = [
        max(len(header), *(len(row[i]) for row in rows)) if rows else len(header)
        for i, header in enumerate(headers)
    ]
    divider = "-+-".join("-" * w for w in widths)
    print(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print(divider)
    for row in rows:
        print(" | ".join(cell.ljust(w) for cell, w in zip(row, widths)))
    print(divider)
    print(f"target: {report.target_url}")
    print(
        f"filled={report.filled} skipped_null={report.skipped_null} "
        f"mismatches={report.mismatches} errors={report.errors} ok={report.ok}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.population.demo",
        usage=USAGE,
        description="Populate the target form from a JSON dump of extracted documents.",
    )
    parser.add_argument("data_file", help="JSON file shaped {'passport': {...}, 'g28': {...}}")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run the browser headless (default follows settings.populate_headed)",
    )
    args = parser.parse_args(argv)

    path = Path(args.data_file)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        print(f"usage: {USAGE}", file=sys.stderr)
        return 2

    try:
        passport, g28 = _load_documents(path)
    except (ValueError, ValidationError) as exc:
        print(f"error: invalid input data: {exc}", file=sys.stderr)
        print(f"usage: {USAGE}", file=sys.stderr)
        return 2

    headed = False if args.headless else None  # None → settings.populate_headed
    report = asyncio.run(populate_form(passport, g28, headed=headed))
    _print_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
