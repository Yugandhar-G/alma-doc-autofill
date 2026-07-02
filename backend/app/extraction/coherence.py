"""Cross-document coherence: does the G-28 beneficiary plausibly match the
passport holder? Fuzzy comparison only — never blocks, only warns. The
orchestrator surfaces these warnings in the review table.
"""
import logging

from rapidfuzz import fuzz

from app.schemas import FieldWarning, G28Data, PassportData

logger = logging.getLogger("alma.extraction.coherence")

# Domain constant: token_sort_ratio below this (0-100) flags a probable
# person mismatch. 85 tolerates diacritics/ordering noise but catches
# genuinely different names.
NAME_MATCH_THRESHOLD: float = 85.0

_COMPARISONS: tuple[tuple[str, str, str], ...] = (
    # (passport attr, g28 beneficiary attr, warning field path)
    ("surname", "family_name", "beneficiary.family_name"),
    ("given_names", "given_name", "beneficiary.given_name"),
)


def check_coherence(passport: PassportData, g28: G28Data) -> list[FieldWarning]:
    """Compare passport name fields against the G-28 beneficiary block.

    Fields that are null on either side are skipped — a null is a valid
    extraction result, not a mismatch.
    """
    warnings: list[FieldWarning] = []
    for passport_attr, g28_attr, field_path in _COMPARISONS:
        passport_value: str | None = getattr(passport, passport_attr)
        g28_value: str | None = getattr(g28.beneficiary, g28_attr)
        if not passport_value or not g28_value:
            continue
        score = fuzz.token_sort_ratio(passport_value.casefold(), g28_value.casefold())
        if score < NAME_MATCH_THRESHOLD:
            warnings.append(
                FieldWarning(
                    field=field_path,
                    message=(
                        f"G-28 beneficiary {g28_attr} does not match the passport "
                        f"{passport_attr} (similarity {score:.0f}/100). "
                        "Verify both documents belong to the same person."
                    ),
                )
            )
    if warnings:
        logger.info("coherence check flagged %d field(s)", len(warnings))
    return warnings
