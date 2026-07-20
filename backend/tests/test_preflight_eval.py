"""Offline preflight eval gate in CI: every synthetic persona classifies
correctly, zero fabricated findings, exit 0. The clean_packet persona is the
fabrication bait — if any check ever invents a finding on it, this fails."""
from app.packages.preflight.eval.personas import PERSONAS, classify
from app.packages.preflight.eval.run import collect_totals, evaluate, gate


async def test_eval_runs_clean_and_gates_zero():
    results, code, report = await evaluate()
    totals = collect_totals(results)
    assert totals["fabricated"] == 0, report
    assert totals["missed"] == 0, report
    assert code == 0
    # Every non-clean persona contributed its expected correct match.
    assert totals["correct"] == sum(len(p.expected) for p in PERSONAS)


async def test_eval_every_persona_matches_expected_exactly():
    results, _, _ = await evaluate()
    by_name = {r["persona"]: r for r in results}
    for persona in PERSONAS:
        result = by_name[persona.name]
        assert set(result["actual"]) == set(persona.expected), persona.name
        assert result["buckets"]["fabricated"] == []
        assert result["buckets"]["missed"] == []


def test_classify_flags_fabrication_and_miss():
    # A finding not expected → fabricated; expected but absent → missed.
    buckets = classify(frozenset({"identity_consistency"}), frozenset({"evidence_completeness"}))
    assert buckets["fabricated"] == ["evidence_completeness"]
    assert buckets["missed"] == ["identity_consistency"]
    assert buckets["correct"] == []


def test_gate_fails_on_fabrication():
    fabricated_result = {
        "persona": "x",
        "buckets": {"correct": [], "fabricated": ["identity_consistency"], "missed": []},
    }
    assert gate([fabricated_result]) == 1
