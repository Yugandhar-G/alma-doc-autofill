"""Phase E2 re-verification of the trace/telemetry masking wall.

The two PII channels stay separate (CLAUDE.md): response bodies + the
session-owner SSE stream may carry real values; Langfuse traces and logs carry
only hashes, ids, counts, and MASKED previews. This suite walks the maskers
over representative payloads and asserts no raw value survives into any
trace-output helper.

Note on the matter/run/inbox path: app/api/matters.py emits NO Langfuse spans
(it opens no request_trace / stage_span), so there is no new trace surface to
mask there — firm isolation on that path is structural (store layer), and its
logs already carry ids/counts only. The guard tests below assert that the
structured trace-output helpers that DO exist (envelope_stats, report_stats)
never leak values, so any future matter-path trace built from the same helpers
inherits the same guarantee.
"""
from app.kernel.observability import count_leaves, mask_leaves, mask_value
from app.observability import envelope_stats, report_stats
from app.schemas import (
    ExtractionEnvelope,
    PopulationEntry,
    PopulationReport,
)

# Raw values that must NEVER appear in any masked/trace output.
RAW_STRINGS = ("GONZALEZ", "Maria", "1990-04-12", "P1234567", "Robotics Lab", "42 Elm St")


def _assert_no_raw(dumped: str) -> None:
    for raw in RAW_STRINGS:
        assert raw not in dumped, f"leaked raw value: {raw}"
    # Also no 4-digit year fragment from the sample dates.
    assert "1990" not in dumped
    assert "2021" not in dumped


# --- mask_value / mask_leaves ----------------------------------------------
def test_dates_render_as_shape_only() -> None:
    assert mask_value("1990-04-12") == "****-**-**"
    assert mask_value("2021-12-31") == "****-**-**"


def test_values_keep_first_char_only() -> None:
    assert mask_value("GONZALEZ").startswith("G")
    assert "ONZALEZ" not in mask_value("GONZALEZ")
    assert mask_value("P1234567").startswith("P")
    assert "1234567" not in mask_value("P1234567")


def test_mask_leaves_masks_nested_pii_and_drops_nulls() -> None:
    payload = {
        "beneficiary": {
            "family_name": "GONZALEZ",
            "given_name": "Maria",
            "date_of_birth": "1990-04-12",
            "middle_name": None,
        },
        "employer": {"name": "Robotics Lab", "since": "2021-12-31"},
        "address": "42 Elm St",
    }
    masked = mask_leaves(payload)
    _assert_no_raw(str(masked))
    # Nulls are dropped (their count belongs in a stat, not the masked tree).
    assert "middle_name" not in masked["beneficiary"]
    # Shape is preserved so the trace still proves normalization ran.
    assert masked["beneficiary"]["date_of_birth"] == "****-**-**"


def test_count_leaves_reports_null_split() -> None:
    read, null = count_leaves({"a": "x", "b": None, "c": {"d": None, "e": "y"}})
    assert (read, null) == (2, 2)


# --- Package-typed trace summarizers ---------------------------------------
def _envelope() -> ExtractionEnvelope:
    return ExtractionEnvelope(
        document_type_requested="passport",
        document_type_detected="passport",
        data={
            "surname": "GONZALEZ",
            "given_names": "Maria",
            "date_of_birth": "1990-04-12",
            "passport_number": "P1234567",
            "middle_names": None,
        },
        warnings=[],
        model_used="test-model",
        source_hash="a" * 64,
    )


def test_envelope_stats_carries_no_raw_value() -> None:
    stats = envelope_stats(_envelope())
    _assert_no_raw(str(stats))
    # Only PII-safe identifiers/counts + masked previews.
    assert stats["fields_read"] == 4
    assert stats["fields_null"] == 1
    assert stats["source_hash"] == "a" * 64
    assert stats["fields"]["surname"] == "G*******"


def test_report_stats_is_counts_only() -> None:
    report = PopulationReport(
        target_url="https://example.test/form",
        entries=[
            PopulationEntry(
                selector="#passport-surname",
                source="passport.surname",
                action="fill",
                status="filled",
                expected="GONZALEZ",  # a real value on the entry...
                actual="GONZALEZ",
            )
        ],
        filled=1,
        ok=True,
    )
    stats = report_stats(report)
    # ...but report_stats must reduce to counts, never echoing expected/actual.
    _assert_no_raw(str(stats))
    assert stats["entries"] == 1
    assert stats["filled"] == 1
    assert "expected" not in str(stats)


def test_trace_helpers_only_expose_safe_identifiers() -> None:
    """Guard: the identifiers a trace helper surfaces are hashes / enums /
    counts — never names or free text. If a helper grows a new key, this test
    forces a conscious check that it is PII-safe."""
    stats = envelope_stats(_envelope())
    allowed_keys = {
        "requested", "detected", "fields_read", "fields_null",
        "fields", "warnings", "model_used", "source_hash",
    }
    assert set(stats) == allowed_keys
    # The one free-form-shaped key ("fields") is fully masked, asserted above.
