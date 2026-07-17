"""Registry integrity — the USCIS knowledge is data, so its shape is testable."""
from app.screener.criteria import (
    CRITERIA,
    CRITERIA_BY_ID,
    EB1A_THRESHOLD,
    O1A_THRESHOLD,
    criteria_for,
    criteria_for_targets,
)


def test_registry_has_ten_criteria_with_unique_ids():
    assert len(CRITERIA) == 10
    assert len(CRITERIA_BY_ID) == 10


def test_o1a_has_eight_criteria_eb1a_has_ten():
    assert len(criteria_for("O1A")) == 8
    assert len(criteria_for("EB1A")) == 10


def test_eb1a_only_criteria_are_exhibitions_and_commercial_success():
    eb1a_only = {s.id for s in CRITERIA if s.applies_to == frozenset({"EB1A"})}
    assert eb1a_only == {"exhibitions", "commercial_success"}


def test_every_criterion_has_regulatory_ref_matching_applicability():
    for spec in CRITERIA:
        if "O1A" in spec.applies_to:
            assert spec.o1a_ref and spec.o1a_ref.startswith("8 CFR 214.2(o)")
        if "EB1A" in spec.applies_to:
            assert spec.eb1a_ref and spec.eb1a_ref.startswith("8 CFR 204.5(h)")


def test_every_criterion_carries_evidence_and_rfe_guidance():
    for spec in CRITERIA:
        assert spec.strong_evidence, spec.id
        assert spec.rfe_patterns, spec.id
        assert spec.description, spec.id


def test_thresholds():
    assert O1A_THRESHOLD == 3
    assert EB1A_THRESHOLD == 3


def test_targets_union():
    assert len(criteria_for_targets(["O1A"])) == 8
    assert len(criteria_for_targets(["O1A", "EB1A"])) == 10
    assert criteria_for_targets([]) == ()
