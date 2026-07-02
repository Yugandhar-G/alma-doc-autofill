"""Read-back verification for the population plane.

After fill.py performs its writes, every FIELD_MAP spec is read back from
the live DOM (`input_value()` for text/date/select controls,
`is_checked()` for checkboxes) and diffed against the intended DOM state
recorded at write time. The diff produces one PopulationEntry per spec:

- ``filled``       write happened (or a checkbox was intentionally left
                   unchecked) and the read-back matches the intent
- ``skipped_null`` source value was null → no interaction; the control is
                   still read back for audit (actual is informational)
- ``mismatch``     read-back differs from the intended state
- ``error``        the write or the read-back raised; message in ``actual``
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from playwright.async_api import Locator, Page

from app.population.field_map import FieldSpec
from app.schemas import PopulationEntry, PopulationReport

logger = logging.getLogger(__name__)

# Canonical DOM-state strings for checkbox expectations/read-backs.
CHECKED = "checked"
UNCHECKED = "unchecked"

WriteStatus = Literal["written", "skipped_null", "error"]


@dataclass(frozen=True)
class PendingWrite:
    """Outcome of the write phase for one FieldSpec, before verification.

    ``expected`` is the DOM-level intended state: the exact text for fills,
    the selected option *value* for selects (e.g. "CA" after selecting the
    label "California"), or CHECKED/UNCHECKED for checkboxes.
    """

    spec: FieldSpec
    status: WriteStatus
    expected: str | None
    error: str | None = None


def locator_for(page: Page, spec: FieldSpec) -> Locator:
    """Resolve a spec to a Locator, applying positional disambiguation.

    ``nth`` handles the planted duplicate-id trap: both Part 3 given-names
    inputs share id/name, so the middle name is addressed positionally.
    """
    loc = page.locator(spec.selector)
    return loc.nth(spec.nth) if spec.nth is not None else loc


async def _read_back(page: Page, spec: FieldSpec) -> str:
    """Read the current DOM state of one control (read-only, no interaction)."""
    loc = locator_for(page, spec)
    if spec.action == "check":
        return CHECKED if await loc.is_checked() else UNCHECKED
    return await loc.input_value()


async def _entry_for(page: Page, write: PendingWrite) -> PopulationEntry:
    spec = write.spec
    base = {"selector": spec.selector, "source": spec.source, "action": spec.action}

    if write.status == "error":
        return PopulationEntry(**base, status="error", expected=write.expected, actual=write.error)

    if write.status == "skipped_null":
        # Audit read: prove the untouched control really was left alone.
        # Best-effort — a failed audit read never fails the run.
        actual: str | None
        try:
            actual = await _read_back(page, spec)
        except Exception as exc:
            logger.warning("audit read-back failed for %s: %s", spec.selector, exc)
            actual = None
        return PopulationEntry(**base, status="skipped_null", expected=None, actual=actual)

    # status == "written": verify the intent landed.
    try:
        actual = await _read_back(page, spec)
    except Exception as exc:
        logger.error("verification read-back failed for %s: %s", spec.selector, exc)
        return PopulationEntry(
            **base, status="error", expected=write.expected,
            actual=f"{type(exc).__name__}: {exc}",
        )
    status = "filled" if actual == write.expected else "mismatch"
    if status == "mismatch":
        logger.error(
            "population mismatch for %s: expected %r, got %r",
            spec.selector, write.expected, actual,
        )
    return PopulationEntry(**base, status=status, expected=write.expected, actual=actual)


async def verify_and_report(
    page: Page, target_url: str, writes: list[PendingWrite]
) -> PopulationReport:
    """Read every spec back, diff, and aggregate into a PopulationReport."""
    entries = [await _entry_for(page, write) for write in writes]
    counts = {status: 0 for status in ("filled", "skipped_null", "mismatch", "error")}
    for entry in entries:
        counts[entry.status] += 1
    return PopulationReport(
        target_url=target_url,
        entries=entries,
        filled=counts["filled"],
        skipped_null=counts["skipped_null"],
        mismatches=counts["mismatch"],
        errors=counts["error"],
        ok=(counts["mismatch"] == 0 and counts["error"] == 0),
    )
