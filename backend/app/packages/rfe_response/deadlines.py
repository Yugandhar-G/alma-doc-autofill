"""Deterministic RFE deadline math — pure code, no clock.

``today`` is passed in (injected into graph state by the API at run start), so
a run is replayable: re-running the deadline node on a checkpoint yields the
same result it did originally. Nothing here calls datetime.now().

Warning bands (calendar days between ``today`` and the response deadline):
- deadline in the past (< 0 days)  → critical: the window has closed
- 0..13 days remaining             → critical: file immediately
- 14..29 days remaining            → warning: prepare now
- 30+ days remaining               → no warning
- deadline null OR unparseable     → None + an explicit "confirm manually"
  message. Absence of a verifiable deadline is stated, never guessed.
"""
from datetime import date

CRITICAL_DAYS = 14
WARNING_DAYS = 30

_UNVERIFIABLE = (
    "Deadline unverifiable — the response-by date could not be read from the "
    "notice. Confirm the deadline manually before relying on this report."
)


def _parse_iso(value: str | None) -> date | None:
    """Parse a normalized YYYY-MM-DD string, or None if absent/unparseable.
    Never raises — an unreadable date is treated exactly like an absent one."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, TypeError):
        return None


def deadline_status(response_deadline: str | None, today: str) -> tuple[int | None, str | None]:
    """(days_remaining, warning) for a response deadline relative to ``today``.

    Returns (None, unverifiable-message) when either date is missing/unparseable
    — the honest "confirm manually" path. Otherwise days_remaining is the signed
    calendar-day delta (negative = past) and warning is the band message (or
    None when 30+ days remain)."""
    deadline = _parse_iso(response_deadline)
    now = _parse_iso(today)
    if deadline is None or now is None:
        return None, _UNVERIFIABLE

    days = (deadline - now).days
    if days < 0:
        return days, (
            f"Response deadline passed {abs(days)} day(s) ago "
            f"({response_deadline}) — the filing window has closed."
        )
    if days < CRITICAL_DAYS:
        return days, (
            f"Critical: {days} day(s) until the response deadline "
            f"({response_deadline}) — assemble and file immediately."
        )
    if days < WARNING_DAYS:
        return days, (
            f"Warning: {days} day(s) until the response deadline "
            f"({response_deadline}) — begin assembling the response now."
        )
    return days, None


def is_critical(days_remaining: int | None) -> bool:
    """A deadline is critical when unverifiable (None) or under CRITICAL_DAYS
    (which includes past-due negatives). Drives the report's ``ok`` gate."""
    return days_remaining is None or days_remaining < CRITICAL_DAYS
