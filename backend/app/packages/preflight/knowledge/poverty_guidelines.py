"""2026 Federal Poverty Guidelines — the I-864 income-sufficiency table.

Source: docs/immigration-ai-market-research.md §3.1 "2026 Poverty Guidelines
(Scraped from USCIS I-864P, July 2, 2026)", 48 Contiguous States + DC. Values
transcribed verbatim from that table; rows this doc does not contain are NOT
invented here. Alaska/Hawaii variants and household sizes beyond the seam are
out of scope for v0 (the source lists only the contiguous-states table plus a
single Alaska/Hawaii example).

Structure: year -> household_size -> {"p100": int, "p125": int}, dollars/year.
For household sizes above the tabulated maximum, the source gives per-person
increments ("Each additional +$5,680 at 100%, +$7,100 at 125%") applied on top
of the largest tabulated row.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class GuidelineIncrement:
    """Per-additional-household-member increment above the tabulated maximum."""

    p100: int
    p125: int


# 48 Contiguous States + DC, 2026. Transcribed from the market-research table.
_GUIDELINES: dict[int, dict[int, dict[str, int]]] = {
    2026: {
        2: {"p100": 19_720, "p125": 24_650},
        3: {"p100": 24_860, "p125": 31_075},
        4: {"p100": 30_000, "p125": 37_500},
        5: {"p100": 35_140, "p125": 43_925},
        6: {"p100": 40_280, "p125": 50_350},
        7: {"p100": 45_420, "p125": 56_775},
        8: {"p100": 50_560, "p125": 63_200},
    },
}

# "Each additional" row from the same source table.
_INCREMENTS: dict[int, GuidelineIncrement] = {
    2026: GuidelineIncrement(p100=5_680, p125=7_100),
}

_MIN_HOUSEHOLD = 2  # the table starts at a household of 2 (sponsor + immigrant)


def threshold(year: int, household_size: int, pct: str = "p125") -> int:
    """The guideline dollar amount for a household size at a percentage band
    ("p100" or "p125"). Sizes above the tabulated maximum extend by the
    published per-person increment.

    Raises ValueError for an unknown year, a household size below the table's
    floor, or an unknown percentage band — a guess here would be a fabricated
    threshold, the worst defect class.
    """
    if year not in _GUIDELINES:
        raise ValueError(f"No poverty guidelines transcribed for year {year}")
    if pct not in ("p100", "p125"):
        raise ValueError(f"Unknown guideline band {pct!r}; expected 'p100' or 'p125'")
    if household_size < _MIN_HOUSEHOLD:
        raise ValueError(
            f"Household size {household_size} below table floor {_MIN_HOUSEHOLD}"
        )
    table = _GUIDELINES[year]
    if household_size in table:
        return table[household_size][pct]
    largest = max(table)
    extra = household_size - largest
    increment = getattr(_INCREMENTS[year], pct)
    return table[largest][pct] + extra * increment
