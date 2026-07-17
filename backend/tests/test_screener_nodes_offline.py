"""Node and graph behavior with the LLM faked — routing, HITL interrupt,
fan-out/fan-in, failure isolation, and the code-counts-model-narrates rule.
No network."""
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.schemas import (
    CriterionAssessment,
    EvidenceMatrix,
    FinalMeritsAssessment,
    IntakeAnswers,
    ProfileSummary,
    SourceRef,
    VisaVerdict,
)
from app.screener.criteria import criteria_for
from app.screener.graph import (
    build_graph,
    fan_out_assessments,
    route_merits,
    route_verification,
)
from app.screener.state import ScreenerState


def _state(visa_targets=("O1A", "EB1A"), assessments=()):
    return ScreenerState(
        session_id="test-session",
        visa_targets=list(visa_targets),
        intake=IntakeAnswers(
            field_of_endeavor="Distributed systems",
            awards=["ACM Award 2024"],
        ),
        assessments=list(assessments),
    )


def _met(criterion_id):
    return CriterionAssessment(
        criterion_id=criterion_id,
        verdict="met",
        reasoning="r",
        citations=[SourceRef(kind="answer", ref="awards[0]")],
    )


class _Namespace:
    """Settings stand-in for pure routing functions."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.fixture
def enrichment_off(monkeypatch):
    monkeypatch.setattr(
        "app.screener.graph.get_settings",
        lambda: _Namespace(screener_web_enrichment=False, gemini_api_key=None),
    )


@pytest.fixture
def fake_llm(monkeypatch, enrichment_off):
    """Patch the shared node LLM seam (common.generate). Returns the call log."""
    calls: list[str] = []

    async def fake_call(settings, prompt, wrapper, **kwargs):
        calls.append(kwargs.get("trace_name", "?"))
        if wrapper is EvidenceMatrix:
            return EvidenceMatrix(
                items=[
                    {
                        "claim": "Received the ACM Award 2024",
                        "criterion_ids": ["awards"],
                        "sources": [{"kind": "answer", "ref": "awards[0]"}],
                    }
                ]
            )
        if wrapper is CriterionAssessment:
            return CriterionAssessment(
                criterion_id="mislabeled-on-purpose",
                verdict="met",
                reasoning="cited evidence maps onto the regulatory language",
                citations=[SourceRef(kind="answer", ref="awards[0]")],
            )
        if wrapper is FinalMeritsAssessment:
            return FinalMeritsAssessment(
                conclusion="favorable",
                reasoning="sustained acclaim",
                citations=[SourceRef(kind="answer", ref="field_of_endeavor")],
            )
        if wrapper is ProfileSummary:
            return ProfileSummary(
                headline="Strong systems researcher with a documented award record.",
                strengths=["distributed systems research"],
                eligibility_drivers=["ACM Award 2024 (awards)"],
                risks=["thin public footprint"],
            )
        return VisaVerdict(
            visa="O1A",
            recommendation="strong",
            confidence="high",
            criteria_met=99,  # deliberately wrong — code must overwrite
            criteria_likely=99,
            summary="synthesized",
        )

    monkeypatch.setattr("app.screener.nodes.common.generate", fake_call)
    return calls


async def _run_through_review(state, edited_matrix=None):
    """Drive the graph across the HITL interrupt: run → pause at review_gate →
    resume with the (optionally edited) matrix → final state values."""
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": state.session_id}}
    first = await graph.ainvoke(state, config=config)
    assert "__interrupt__" in first, "graph must pause for human review"
    matrix = first["__interrupt__"][0].value["matrix"]
    resume_value = edited_matrix if edited_matrix is not None else matrix
    return await graph.ainvoke(Command(resume=resume_value), config=config)


# ---- routing (pure functions) ----

def test_fan_out_covers_union_of_targets():
    assert len(fan_out_assessments(_state(("O1A",)))) == 8
    assert len(fan_out_assessments(_state(("O1A", "EB1A")))) == 10
    assert len(fan_out_assessments(_state(("EB1A",)))) == 10


def test_merits_gate_requires_eb1a_target():
    strong = [_met(s.id) for s in criteria_for("EB1A")[:3]]
    assert route_merits(_state(("O1A",), strong)) == "verdict"
    assert route_merits(_state(("O1A", "EB1A"), strong)) == "final_merits"


def test_merits_gate_requires_three_strong_eb1a_criteria():
    two = [_met("awards"), _met("judging")]
    assert route_merits(_state(("EB1A",), two)) == "verdict"
    three = [*two, _met("scholarly_articles")]
    assert route_merits(_state(("EB1A",), three)) == "final_merits"


def test_merits_gate_ignores_weak_and_not_met():
    weak = [
        CriterionAssessment(criterion_id=c, verdict="weak", reasoning="r")
        for c in ("awards", "judging", "membership", "high_salary")
    ]
    assert route_merits(_state(("EB1A",), weak)) == "verdict"


def test_enrichment_route_respects_flag_key_and_matrix(monkeypatch):
    state = _state()
    state = state.model_copy(
        update={
            "matrix": EvidenceMatrix(
                items=[
                    {
                        "claim": "c",
                        "criterion_ids": ["awards"],
                        "sources": [{"kind": "answer", "ref": "awards[0]"}],
                    }
                ]
            )
        }
    )
    cases = [
        (dict(screener_web_enrichment=True, gemini_api_key="k"), "verify_profile"),
        (dict(screener_web_enrichment=False, gemini_api_key="k"), "plan_assessments"),
        (dict(screener_web_enrichment=True, gemini_api_key=None), "plan_assessments"),
    ]
    for settings_kw, expected in cases:
        monkeypatch.setattr(
            "app.screener.graph.get_settings", lambda kw=settings_kw: _Namespace(**kw)
        )
        assert route_verification(state) == expected
    # No reviewed claims → nothing to verify.
    monkeypatch.setattr(
        "app.screener.graph.get_settings",
        lambda: _Namespace(screener_web_enrichment=True, gemini_api_key="k"),
    )
    assert route_verification(_state()) == "plan_assessments"


# ---- full graph with fake LLM (HITL crossed with the unedited matrix) ----

async def test_graph_end_to_end_counts_come_from_code(fake_llm):
    result = await _run_through_review(_state())
    report = result["report"]
    assert len(report.assessments) == 10
    # Node must relabel the model's wrong criterion_id to its own lane.
    assert {a.criterion_id for a in report.assessments} == {
        s.id for s in criteria_for("EB1A")
    }
    by_visa = {v.visa: v for v in report.verdicts}
    # The fake returned criteria_met=99; code recounts.
    assert by_visa["O1A"].criteria_met == 8
    assert by_visa["EB1A"].criteria_met == 10
    assert report.final_merits is not None
    assert "gemini.screener.merits" in fake_llm
    assert "gemini.screener.compile" in fake_llm


async def test_graph_o1a_only_skips_merits(fake_llm):
    result = await _run_through_review(_state(("O1A",)))
    report = result["report"]
    assert len(report.assessments) == 8
    assert report.final_merits is None
    assert "gemini.screener.merits" not in fake_llm


async def test_review_edit_is_revalidated_and_fabricated_source_stripped(fake_llm):
    """A user edit that cites a nonexistent answer is stripped at resume;
    the edited claim with no surviving source is dropped."""
    edited = {
        "items": [
            {
                "claim": "Edited claim with fabricated source",
                "criterion_ids": ["awards"],
                "sources": [{"kind": "answer", "ref": "not_a_real_answer"}],
            },
            {
                "claim": "Edited claim with real source",
                "criterion_ids": ["judging"],
                "sources": [{"kind": "answer", "ref": "awards[0]"}],
            },
        ],
        "unmapped_docs": [],
    }
    result = await _run_through_review(_state(("O1A",)), edited_matrix=edited)
    matrix = result["matrix"]
    assert [i.claim for i in matrix.items] == ["Edited claim with real source"]
    assert any(w.field == "matrix.items" for w in result["report"].warnings)


async def test_disclaimer_is_constant_and_present(fake_llm):
    result = await _run_through_review(_state(("O1A",)))
    assert "not a legal determination" in result["report"].disclaimer


async def test_single_criterion_failure_degrades_not_aborts(monkeypatch, fake_llm):
    """One criterion's model call failing yields not_met + warning for that
    lane; the other seven still assess (slot isolation)."""

    async def failing_call(settings, prompt, wrapper, **kwargs):
        if kwargs.get("source_ref") == "awards":
            raise RuntimeError("boom")
        if wrapper is EvidenceMatrix:
            return EvidenceMatrix()
        if wrapper is CriterionAssessment:
            return CriterionAssessment(
                criterion_id="x",
                verdict="met",
                reasoning="r",
                citations=[SourceRef(kind="answer", ref="awards[0]")],
            )
        if wrapper is FinalMeritsAssessment:
            return FinalMeritsAssessment(conclusion="favorable", reasoning="r")
        if wrapper is ProfileSummary:
            return ProfileSummary(headline="h")
        return VisaVerdict(
            visa="O1A", recommendation="strong", confidence="high", summary="s"
        )

    monkeypatch.setattr("app.screener.nodes.common.generate", failing_call)
    result = await _run_through_review(_state(("O1A",)))
    report = result["report"]
    assert len(report.assessments) == 8
    awards = next(a for a in report.assessments if a.criterion_id == "awards")
    assert awards.verdict == "not_met"
    assert any(w.field == "assessments.awards" for w in report.warnings)


async def test_uncited_positive_verdicts_are_downgraded_in_report(monkeypatch, fake_llm):
    """A model that claims 'met' with a fabricated citation ends up not_met."""

    async def fabricating_call(settings, prompt, wrapper, **kwargs):
        if wrapper is EvidenceMatrix:
            return EvidenceMatrix()
        if wrapper is CriterionAssessment:
            return CriterionAssessment(
                criterion_id="x",
                verdict="met",
                reasoning="trust me",
                citations=[SourceRef(kind="answer", ref="phd_from_nowhere")],
            )
        if wrapper is FinalMeritsAssessment:
            return FinalMeritsAssessment(conclusion="favorable", reasoning="r")
        if wrapper is ProfileSummary:
            return ProfileSummary(headline="h")
        return VisaVerdict(
            visa="O1A", recommendation="strong", confidence="high", summary="s"
        )

    monkeypatch.setattr("app.screener.nodes.common.generate", fabricating_call)
    result = await _run_through_review(_state(("O1A",)))
    report = result["report"]
    assert all(a.verdict == "not_met" for a in report.assessments)
    # Counts were reconciled post-audit and the mismatch was flagged; the
    # 'strong' narrative was capped by the criteria arithmetic (0 met < 3).
    assert report.verdicts[0].criteria_met == 0
    assert report.verdicts[0].recommendation == "weak"
    assert any(w.field == "verdicts.O1A" for w in report.warnings)


def test_recommendation_cap_is_pure_arithmetic():
    from app.screener.nodes.report import _cap_recommendation

    def verdict(rec, visa="O1A"):
        return VisaVerdict(visa=visa, recommendation=rec, confidence="high", summary="s")

    # Below threshold: possible/strong collapse to weak.
    capped, warning = _cap_recommendation(verdict("possible"), met=1, likely=1, one_time_award=False)
    assert capped.recommendation == "weak" and warning is not None
    # Threshold met only via likely: strong collapses to possible.
    capped, _ = _cap_recommendation(verdict("strong"), met=2, likely=2, one_time_award=False)
    assert capped.recommendation == "possible"
    # Threshold met outright: untouched.
    capped, warning = _cap_recommendation(verdict("strong"), met=3, likely=0, one_time_award=False)
    assert capped.recommendation == "strong" and warning is None
    # One-time major award bypasses the count by regulation.
    capped, warning = _cap_recommendation(verdict("strong"), met=0, likely=0, one_time_award=True)
    assert capped.recommendation == "strong" and warning is None
    # Conservative verdicts are never touched.
    capped, warning = _cap_recommendation(verdict("weak"), met=0, likely=0, one_time_award=False)
    assert capped.recommendation == "weak" and warning is None
