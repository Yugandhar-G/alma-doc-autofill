"""Deterministic report assembly: citation audit, count reconciliation,
constant disclaimer. No LLM call in this node — the last word is code."""
import logging

from app.schemas import FieldWarning, ScreenerReport, VisaVerdict
from app.screener.citations import audit_assessment, audit_final_merits
from app.screener.criteria import (
    EB1A_THRESHOLD,
    NIW_THRESHOLD,
    O1A_THRESHOLD,
    criteria_for,
)
from app.screener.intake import answer_index
from app.screener.nodes.common import count_verdicts, emit
from app.screener.state import ScreenerState

logger = logging.getLogger("yunaki.screener.report")

_THRESHOLDS = {"O1A": O1A_THRESHOLD, "EB1A": EB1A_THRESHOLD, "NIW": NIW_THRESHOLD}


def _cap_recommendation(
    verdict: VisaVerdict, met: int, likely: int, one_time_award: bool
) -> tuple[VisaVerdict, FieldWarning | None]:
    """Deterministic ceiling on the model's narrative from criteria arithmetic.

    O-1A / EB-1A (Kazarian step 1): a below-threshold count cannot be
    'possible' or better, and 'strong' requires the threshold in outright met
    criteria. The one-time major-award path bypasses the count by regulation.

    NIW: all three Dhanasar prongs are REQUIRED, so the threshold equals the
    prong count — any prong short of met/likely (met + likely < 3) caps to
    'weak', and 'strong' still requires all three outright met. There is no
    one-time-award bypass for NIW (that path is an extraordinary-ability
    concept, irrelevant to the national-interest waiver)."""
    if one_time_award and verdict.visa != "NIW":
        return verdict, None
    threshold = _THRESHOLDS[verdict.visa]
    capped = verdict.recommendation
    if met + likely < threshold and capped in ("strong", "possible"):
        capped = "weak"
    elif met < threshold and capped == "strong":
        capped = "possible"
    if capped == verdict.recommendation:
        return verdict, None
    warning = FieldWarning(
        field=f"verdicts.{verdict.visa}",
        message=f"Recommendation '{verdict.recommendation}' exceeded what the "
        f"criteria arithmetic supports ({met} met / {likely} likely vs "
        f"threshold {threshold}); capped to '{capped}'.",
    )
    return verdict.model_copy(update={"recommendation": capped}), warning


async def assemble_report(state: ScreenerState) -> dict:
    valid_answer_ids = frozenset(
        answer_index(state.intake).keys() if state.intake else ()
    )
    grounded_urls = frozenset(state.grounded_urls)

    audited = []
    new_warnings: list[FieldWarning] = []
    for assessment in state.assessments:
        checked, warnings = audit_assessment(
            assessment, valid_answer_ids, state.evidence_docs, grounded_urls
        )
        audited.append(checked)
        new_warnings.extend(warnings)

    merits = state.final_merits
    if merits is not None:
        merits, merit_warnings = audit_final_merits(
            merits, valid_answer_ids, state.evidence_docs, grounded_urls
        )
        new_warnings.extend(merit_warnings)

    # Counts may have shifted if the audit downgraded assessments; reconcile
    # and flag (never silently keep a recommendation the numbers no longer back).
    one_time_award = bool(state.intake and state.intake.one_time_major_award)
    verdicts = []
    for v in state.verdicts:
        applicable = tuple(spec.id for spec in criteria_for(v.visa))
        met, likely = count_verdicts(audited, applicable)
        if (met, likely) != (v.criteria_met, v.criteria_likely):
            new_warnings.append(
                FieldWarning(
                    field=f"verdicts.{v.visa}",
                    message="Criteria counts changed after the citation audit "
                    f"({v.criteria_met}/{v.criteria_likely} → {met}/{likely}); "
                    "the recommendation predates the audit — review with care.",
                )
            )
        updated = v.model_copy(update={"criteria_met": met, "criteria_likely": likely})
        updated, cap_warning = _cap_recommendation(updated, met, likely, one_time_award)
        if cap_warning is not None:
            new_warnings.append(cap_warning)
        verdicts.append(updated)

    report = ScreenerReport(
        session_id=state.session_id,
        visa_targets=state.visa_targets,
        profile_summary=state.profile_summary,
        verification=state.verification,
        verdicts=verdicts,
        assessments=audited,
        final_merits=merits,
        exhibit_index=state.exhibit_index,
        warnings=[*state.warnings, *new_warnings],
    )
    emit(
        {
            "type": "finding",
            "node": "assemble_report",
            "audited_assessments": len(audited),
            "citations_stripped_warnings": len(new_warnings),
        }
    )
    logger.info(
        "screener report assembled session=%s assessments=%d warnings=%d",
        state.session_id, len(audited), len(report.warnings),
    )
    return {"report": report, "warnings": new_warnings}
