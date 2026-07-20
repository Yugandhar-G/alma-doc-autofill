"""Offline RFE-response eval gate in CI: every synthetic persona classifies
correctly, zero fabricated labels, exit 0. The clean_notice persona is the
fabrication bait — if the audit ever lets a fabricated-ground item survive, or
the deadline math guesses a null deadline, those labels land in the fabricated
bucket and this fails."""
from app.packages.rfe_response.eval.personas import PERSONAS, classify
from app.packages.rfe_response.eval.run import collect_totals, evaluate, gate


async def test_eval_runs_clean_and_gates_zero():
    results, code, report = await evaluate()
    totals = collect_totals(results)
    assert totals["fabricated"] == 0, report
    assert totals["missed"] == 0, report
    assert code == 0
    assert totals["correct"] == sum(len(p.expected) for p in PERSONAS)


async def test_eval_every_persona_matches_expected_exactly():
    results, _, _ = await evaluate()
    by_name = {r["persona"]: r for r in results}
    for persona in PERSONAS:
        result = by_name[persona.name]
        assert set(result["actual"]) == set(persona.expected), (persona.name, result)
        assert result["buckets"]["fabricated"] == []
        assert result["buckets"]["missed"] == []


def test_classify_flags_survived_fabrication_as_fabricated():
    # A run that let a fabricated ground survive produces a label no persona
    # expects → fabricated bucket.
    buckets = classify(frozenset({"clean_map"}), frozenset({"survived_fabricated_ground"}))
    assert "survived_fabricated_ground" in buckets["fabricated"]
    assert buckets["missed"] == ["clean_map"]


def test_gate_fails_on_fabrication():
    fabricated = {
        "persona": "x",
        "buckets": {"correct": [], "fabricated": ["deadline_guessed"], "missed": []},
    }
    assert gate([fabricated]) == 1
