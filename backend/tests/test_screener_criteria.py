"""Registry integrity — the USCIS knowledge is data, so its shape is testable."""
from app.screener.criteria import (
    CRITERIA,
    CRITERIA_BY_ID,
    EB1A_THRESHOLD,
    NIW_THRESHOLD,
    O1A_THRESHOLD,
    criteria_for,
    criteria_for_targets,
)

# 10 extraordinary-ability criteria (O-1A/EB-1A) + 3 Dhanasar NIW prongs.
_EXPECTED_CRITERIA = 13
_NIW_PRONGS = {"niw_merit_importance", "niw_well_positioned", "niw_benefit_waiver"}


def test_registry_criteria_have_unique_ids():
    assert len(CRITERIA) == _EXPECTED_CRITERIA
    assert len(CRITERIA_BY_ID) == _EXPECTED_CRITERIA


def test_o1a_has_eight_criteria_eb1a_has_ten():
    assert len(criteria_for("O1A")) == 8
    assert len(criteria_for("EB1A")) == 10


def test_niw_has_three_dhanasar_prongs():
    niw = criteria_for("NIW")
    assert len(niw) == 3
    assert {s.id for s in niw} == _NIW_PRONGS
    # NIW prongs are their own framework — never O-1A/EB-1A criteria.
    for spec in niw:
        assert spec.applies_to == frozenset({"NIW"})
        assert spec.o1a_ref is None and spec.eb1a_ref is None


def test_eb1a_only_criteria_are_exhibitions_and_commercial_success():
    eb1a_only = {s.id for s in CRITERIA if s.applies_to == frozenset({"EB1A"})}
    assert eb1a_only == {"exhibitions", "commercial_success"}


def test_every_criterion_has_regulatory_ref_matching_applicability():
    for spec in CRITERIA:
        if "O1A" in spec.applies_to:
            assert spec.o1a_ref and spec.o1a_ref.startswith("8 CFR 214.2(o)")
        if "EB1A" in spec.applies_to:
            assert spec.eb1a_ref and spec.eb1a_ref.startswith("8 CFR 204.5(h)")
        if "NIW" in spec.applies_to:
            assert spec.niw_ref and "Dhanasar" in spec.niw_ref


def test_every_criterion_carries_evidence_and_rfe_guidance():
    for spec in CRITERIA:
        assert spec.strong_evidence, spec.id
        assert spec.rfe_patterns, spec.id
        assert spec.description, spec.id


def test_thresholds():
    assert O1A_THRESHOLD == 3
    assert EB1A_THRESHOLD == 3
    assert NIW_THRESHOLD == 3


def test_targets_union():
    assert len(criteria_for_targets(["O1A"])) == 8
    assert len(criteria_for_targets(["O1A", "EB1A"])) == 10
    assert len(criteria_for_targets(["NIW"])) == 3
    # NIW is disjoint from the extraordinary-ability set → strict addition.
    assert len(criteria_for_targets(["EB1A", "NIW"])) == 13
    assert criteria_for_targets([]) == ()
