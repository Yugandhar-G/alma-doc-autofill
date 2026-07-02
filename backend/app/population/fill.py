"""Playwright population engine (Agent B).

Contract (see __init__.py): iterate FIELD_MAP — the only source of
selectors — resolve each spec's dotted source against the extracted
documents, write via fill()/select_option()/check() ONLY, skip nulls
without touching the control, then hand off to verify.py which reads
every control back and diffs (PopulationReport).

Navigation is locked to settings.target_form_url; tests may override via
the keyword-only ``target_url`` (file:// snapshot). Never clicks, never
unchecks, never sets values through JS, never goes near signature or
Part 4/5 controls (they are structurally absent from FIELD_MAP).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from playwright.async_api import Page, async_playwright

from app.config import get_settings
from app.population.field_map import FIELD_MAP, FieldSpec
from app.population.verify import (
    CHECKED,
    UNCHECKED,
    PendingWrite,
    locator_for,
    verify_and_report,
)
from app.schemas import G28Data, PassportData, PopulationReport

logger = logging.getLogger(__name__)

# Budget split for populate_form (fractions of settings.populate_timeout_ms):
# page navigation gets a quarter; everything else is divided across the write
# and verify passes. See populate_form's docstring for the full model.
_GOTO_FRACTION = 0.25
_MARGIN_FRACTION = 0.1


def resolve_source(sources: dict[str, Any], dotted: str) -> Any:
    """Walk a dotted path like 'g28.attorney.city' through nested dicts.

    A missing document (None subtree, e.g. no G-28 uploaded) resolves every
    path beneath it to None. An unknown key is a FIELD_MAP/schema drift
    defect and raises loudly (caught per-field → status "error").
    """
    node: Any = sources
    for part in dotted.split("."):
        if node is None:
            return None
        if not isinstance(node, dict):
            raise ValueError(
                f"cannot resolve {dotted!r}: {part!r} is beneath a non-mapping value"
            )
        if part not in node:
            raise KeyError(f"unknown source path {dotted!r}: no key {part!r}")
        node = node[part]
    return node


def _checkbox_intent(spec: FieldSpec, value: Any) -> bool:
    """Decide whether a 'check' spec's box should be checked for this value.

    - Boolean sources use ``check_when``: check only when value == check_when
      (e.g. subject_to_discipline False → #not-subject, True → #am-subject).
    - String sources (g28.attorney.apt_ste_flr ∈ {apt, ste, flr}) check the
      box whose selector id equals the value.
    A False intent means the box is left alone — never unchecked.
    """
    if isinstance(value, bool):
        if spec.check_when is None:
            raise ValueError(f"{spec.selector}: boolean check source requires check_when")
        return value == spec.check_when
    if isinstance(value, str):
        return value == spec.selector.removeprefix("#")
    raise TypeError(
        f"{spec.selector}: unsupported source type {type(value).__name__} for check action"
    )


def _require_str(spec: FieldSpec, value: Any) -> str:
    if not isinstance(value, str):
        # No value in the message — it flows into both the report and the log.
        raise TypeError(
            f"{spec.selector}: action {spec.action!r} needs a string source, "
            f"got {type(value).__name__}"
        )
    return value


async def _apply(page: Page, spec: FieldSpec, value: Any) -> PendingWrite:
    """Perform the single allowed interaction for one spec (non-null value)."""
    loc = locator_for(page, spec)

    if spec.action == "fill":
        text = _require_str(spec, value)
        await loc.fill(text)
        return PendingWrite(spec, "written", expected=text)

    if spec.action == "select_label":
        # Option labels are full names, values are codes (e.g. California/CA);
        # select_option returns the selected VALUES → that is the DOM-level
        # expectation the read-back must match.
        selected = await loc.select_option(label=_require_str(spec, value))
        return PendingWrite(spec, "written", expected=selected[0] if selected else "")

    if spec.action == "select_value":
        selected = await loc.select_option(_require_str(spec, value))
        return PendingWrite(spec, "written", expected=selected[0] if selected else "")

    if spec.action == "check":
        if _checkbox_intent(spec, value):
            await loc.check()
            return PendingWrite(spec, "written", expected=CHECKED)
        # Intent is "leave unchecked": no interaction, but still verified —
        # the read-back must find the box unchecked.
        return PendingWrite(spec, "written", expected=UNCHECKED)

    raise ValueError(f"{spec.selector}: unknown action {spec.action!r}")


async def _write_all(page: Page, sources: dict[str, Any]) -> list[PendingWrite]:
    """Apply every FIELD_MAP spec; per-field failures never abort the run."""
    writes: list[PendingWrite] = []
    for spec in FIELD_MAP:
        try:
            value = resolve_source(sources, spec.source)
            if value is None:
                writes.append(PendingWrite(spec, "skipped_null", expected=None))
                continue
            writes.append(await _apply(page, spec, value))
        except Exception as exc:
            # Log the failure class only; the full message (which may echo an
            # extracted value, e.g. a missing select option) goes only to the
            # user-facing report entry.
            logger.error(
                "population write failed for %s (%s): %s",
                spec.selector, spec.source, type(exc).__name__,
            )
            writes.append(
                PendingWrite(
                    spec, "error", expected=None, error=f"{type(exc).__name__}: {exc}"
                )
            )
    return writes


async def populate_form(
    passport: PassportData | None,
    g28: G28Data | None,
    headed: bool | None = None,
    *,
    target_url: str | None = None,
) -> PopulationReport:
    """Fill the target form from extracted documents and verify every write.

    ``headed`` None → settings.populate_headed. ``target_url`` None →
    settings.target_form_url (tests point it at the file:// snapshot).

    Budget model (all derived from settings.populate_timeout_ms, no
    literals): goto gets _GOTO_FRACTION of the budget; the remainder is
    split across TWO passes over FIELD_MAP (write, then verify read-back),
    since a stalled selector costs its slice in each pass. The outer
    timeout is the sum of those parts plus _MARGIN_FRACTION, so worst-case
    per-field stalls still end with a full report instead of a mid-run
    TimeoutError that loses everything.
    """
    settings = get_settings()
    url = target_url if target_url is not None else settings.target_form_url
    run_headed = settings.populate_headed if headed is None else headed
    timeout_ms = settings.populate_timeout_ms
    goto_ms = int(timeout_ms * _GOTO_FRACTION)
    per_action_ms = max(1, (timeout_ms - goto_ms) // (2 * len(FIELD_MAP)))
    outer_seconds = (
        (goto_ms + 2 * len(FIELD_MAP) * per_action_ms) * (1 + _MARGIN_FRACTION) / 1000
    )

    sources: dict[str, Any] = {
        "passport": passport.model_dump() if passport is not None else None,
        "g28": g28.model_dump() if g28 is not None else None,
    }

    logger.info("populating %s (headed=%s, %d specs)", url, run_headed, len(FIELD_MAP))
    async with asyncio.timeout(outer_seconds):
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not run_headed)
            try:
                page = await browser.new_page()
                page.set_default_timeout(per_action_ms)
                await page.goto(url, timeout=goto_ms)
                writes = await _write_all(page, sources)
                report = await verify_and_report(page, url, writes)
            finally:
                await browser.close()

    logger.info(
        "population done: filled=%d skipped_null=%d mismatches=%d errors=%d ok=%s",
        report.filled, report.skipped_null, report.mismatches, report.errors, report.ok,
    )
    return report
