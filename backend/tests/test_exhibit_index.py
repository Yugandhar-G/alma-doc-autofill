"""Exhibit-index derivation (pure code) and NIW registry/cap/routing.

The exhibit index is built from the AUDITED matrix: a stripped ref can never
become an exhibit, numbering is stable (registry → matrix → source order), and
gaps are exactly the applicable criteria no surviving evidence covers. NIW adds
three required Dhanasar prongs with no Kazarian step and no one-time-award
bypass. No network in this module."""
from app.schemas import (
    EvidenceDocRecord,
    EvidenceMatrix,
    SourceRef,
    VisaVerdict,
)
from app.screener.criteria import criteria_for, criteria_for_targets
from app.screener.exhibits import build_exhibit_index
from app.screener.graph import route_merits
from app.screener.nodes.report import _cap_recommendation
from app.screener.state import ScreenerState

_DOC_HASH = "a" * 64
_O1A_IDS = [spec.id for spec in criteria_for("O1A")]


def _matrix(items):
    return EvidenceMatrix.model_validate({"items": items, "unmapped_docs": []})


def _docs():
    return [
        EvidenceDocRecord(
            source_hash=_DOC_HASH,
            document_kind_detected="award",
            title="MICCAI Best Paper",
            key_facts=["Won Best Paper Award at MICCAI 2023"],
        )
    ]


def _valid_answers():
    return frozenset({"awards[0]"})


# ---- pure derivation ----

def test_numbering_is_stable_registry_then_matrix_then_source_order():
    matrix = _matrix(
        [
            {
                "claim": "cA",
                "criterion_ids": ["awards", "judging"],
                "sources": [{"kind": "answer", "ref": "awards[0]"}],
            },
            {
                "claim": "cB",
                "criterion_ids": ["awards"],
                "sources": [
                    {"kind": "doc", "ref": _DOC_HASH, "excerpt": "Won Best Paper Award"}
                ],
            },
        ]
    )
    index = build_exhibit_index(
        matrix, _O1A_IDS, _valid_answers(), _docs(), frozenset()
    )
    # awards comes before judging in the registry; within awards, matrix order
    # (cA then cB); judging re-lists cA. Numbering is 1..N across criteria.
    assert [(e.exhibit_no, e.criterion_id, e.claim) for e in index.entries] == [
        ("1", "awards", "cA"),
        ("2", "awards", "cB"),
        ("3", "judging", "cA"),
    ]
    doc_entry = next(e for e in index.entries if e.claim == "cB")
    assert doc_entry.source_kind == "doc" and doc_entry.doc_ref == _DOC_HASH
    answer_entry = index.entries[0]
    assert answer_entry.source_kind == "answer" and answer_entry.doc_ref is None


def test_stripped_ref_never_becomes_an_exhibit():
    """Fabrication bait: a claim whose only source is a fabricated answer ref
    yields no exhibit entry (the same audit assemble_report runs)."""
    matrix = _matrix(
        [
            {
                "claim": "real",
                "criterion_ids": ["awards"],
                "sources": [{"kind": "answer", "ref": "awards[0]"}],
            },
            {
                "claim": "fabricated",
                "criterion_ids": ["awards"],
                "sources": [{"kind": "answer", "ref": "phd_from_nowhere"}],
            },
            {
                "claim": "bad-doc-excerpt",
                "criterion_ids": ["awards"],
                "sources": [
                    {"kind": "doc", "ref": _DOC_HASH, "excerpt": "never appeared in the doc"}
                ],
            },
        ]
    )
    index = build_exhibit_index(
        matrix, _O1A_IDS, _valid_answers(), _docs(), frozenset()
    )
    assert [e.claim for e in index.entries] == ["real"]


def test_gaps_are_exactly_uncovered_applicable_criteria():
    matrix = _matrix(
        [
            {
                "claim": "cA",
                "criterion_ids": ["awards"],
                "sources": [{"kind": "answer", "ref": "awards[0]"}],
            }
        ]
    )
    index = build_exhibit_index(
        matrix, _O1A_IDS, _valid_answers(), _docs(), frozenset()
    )
    assert index.gaps == [cid for cid in _O1A_IDS if cid != "awards"]
    # A criterion with a surviving entry is never a gap.
    assert "awards" not in index.gaps


def test_empty_or_missing_matrix_makes_every_applicable_criterion_a_gap():
    for matrix in (None, _matrix([])):
        index = build_exhibit_index(
            matrix, _O1A_IDS, _valid_answers(), _docs(), frozenset()
        )
        assert index.entries == []
        assert index.gaps == _O1A_IDS


def test_web_source_needs_a_grounded_url_to_survive():
    matrix = _matrix(
        [
            {
                "claim": "web-claim",
                "criterion_ids": ["awards"],
                "sources": [{"kind": "web", "ref": "https://example.com/profile"}],
            }
        ]
    )
    # Not grounded → stripped → no entry, awards is a gap.
    absent = build_exhibit_index(matrix, _O1A_IDS, _valid_answers(), _docs(), frozenset())
    assert absent.entries == []
    assert "awards" in absent.gaps
    # Grounded → survives as a web entry with no doc_ref.
    present = build_exhibit_index(
        matrix, _O1A_IDS, _valid_answers(), _docs(),
        frozenset({"https://example.com/profile"}),
    )
    assert [e.source_kind for e in present.entries] == ["web"]
    assert present.entries[0].doc_ref is None


# ---- NIW registry + cap + routing ----

def test_niw_criteria_for_targets_returns_three_prongs():
    prongs = criteria_for_targets(["NIW"])
    assert [s.id for s in prongs] == [
        "niw_merit_importance",
        "niw_well_positioned",
        "niw_benefit_waiver",
    ]


def _verdict(rec, visa="NIW"):
    return VisaVerdict(visa=visa, recommendation=rec, confidence="high", summary="s")


def test_niw_single_not_met_prong_caps_recommendation_at_weak():
    # Two prongs met/likely, one not_met → met+likely = 2 < 3 → capped to weak.
    capped, warning = _cap_recommendation(
        _verdict("strong"), met=2, likely=0, one_time_award=False
    )
    assert capped.recommendation == "weak" and warning is not None
    capped, warning = _cap_recommendation(
        _verdict("possible"), met=1, likely=1, one_time_award=False
    )
    assert capped.recommendation == "weak" and warning is not None


def test_niw_all_three_prongs_met_leaves_strong_untouched():
    capped, warning = _cap_recommendation(
        _verdict("strong"), met=3, likely=0, one_time_award=False
    )
    assert capped.recommendation == "strong" and warning is None
    # All three cleared but via a mix of met/likely → strong collapses to possible.
    capped, _ = _cap_recommendation(
        _verdict("strong"), met=2, likely=1, one_time_award=False
    )
    assert capped.recommendation == "possible"


def test_niw_ignores_the_one_time_award_bypass():
    """The Nobel-class one-time-award path is an extraordinary-ability
    concept; it must never lift an under-supported NIW recommendation."""
    capped, warning = _cap_recommendation(
        _verdict("strong"), met=2, likely=0, one_time_award=True
    )
    assert capped.recommendation == "weak" and warning is not None
    # Same input, EB-1A: the bypass DOES apply (unchanged behavior).
    capped, warning = _cap_recommendation(
        _verdict("strong", visa="EB1A"), met=2, likely=0, one_time_award=True
    )
    assert capped.recommendation == "strong" and warning is None


def test_route_merits_is_eb1a_only_and_niw_never_triggers_final_merits():
    def state(targets, assessments=()):
        return ScreenerState(
            session_id="t", visa_targets=list(targets), assessments=list(assessments)
        )

    # NIW-only never opens the Kazarian step-2 gate.
    assert route_merits(state(("NIW",))) == "verdict"
    # NIW alongside EB-1A does not disturb the EB-1A gate: no strong EB-1A
    # criteria → verdict; the presence of NIW is irrelevant to the routing.
    assert route_merits(state(("EB1A", "NIW"))) == "verdict"
