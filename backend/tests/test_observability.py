"""Masking policy tests: trace output must show field *shape* as guardrail
evidence while never carrying a recoverable value."""
from app.observability import envelope_stats, mask_value
from app.schemas import ExtractionEnvelope


def test_mask_value_keeps_first_char_only():
    assert mask_value("GONZALEZ") == "G*******"
    assert mask_value("X1234567") == "X*******"


def test_mask_value_shows_date_shape_not_date():
    assert mask_value("1990-04-12") == "****-**-**"


def test_mask_value_single_char_and_bool_reveal_nothing():
    assert mask_value("F") == "*"
    assert mask_value(True) == "•"
    assert mask_value(False) == "•"


def test_mask_value_caps_length_leak():
    assert len(mask_value("a" * 40)) <= 12


def make_envelope(data: dict) -> ExtractionEnvelope:
    return ExtractionEnvelope(
        document_type_requested="passport",
        document_type_detected="passport",
        data=data,
        warnings=[],
        model_used="test-model",
        source_hash="a" * 64,
    )


def test_envelope_stats_masks_every_leaf_and_skips_nulls():
    stats = envelope_stats(
        make_envelope(
            {
                "surname": "GONZALEZ",
                "date_of_birth": "1990-04-12",
                "middle_names": None,
                "nested": {"family_name": "Smith"},
            }
        )
    )
    fields = stats["fields"]
    assert fields["surname"] == "G*******"
    assert fields["date_of_birth"] == "****-**-**"
    assert "middle_names" not in fields
    assert fields["nested"]["family_name"] == "S****"
    # No raw value may appear anywhere in the trace payload.
    dumped = str(stats)
    for raw in ("GONZALEZ", "1990", "Smith"):
        assert raw not in dumped
