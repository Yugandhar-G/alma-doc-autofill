"""Schema lint: every Pydantic model that doubles as a Gemini response_schema
must satisfy Gemini structured-output constraints (offline, no API calls).

The rules (verified against live Gemini, see EvidenceMatrix.items):
(a) no discriminated unions anywhere (pydantic ``discriminator``),
(b) no maxItems/max_length on any list-of-BaseModel field — Gemini rejects
    maxItems on lists of nested objects with 400 INVALID_ARGUMENT; caps on
    scalar lists (list[str] etc.) are fine,
(c) the model serializes via model_json_schema().

Written generically: RESPONSE_SCHEMA_MODELS is the one list to extend when a
future package adds response-schema models — every nested model is walked
recursively with a visited set, so listing the roots is enough.

The lint walk and per-rule predicates live in app.kernel.schema_lint so the
package-author acceptance pipeline enforces byte-identical rules on candidate
packages. This module keeps the installed-model roster and the pytest bodies.
"""
import pytest
from pydantic import BaseModel

from app.kernel.schema_lint import (
    all_models,
    discriminator_offenders,
    json_schema_ok,
    max_items_offenders,
)
from app.packages.matter_intake.schemas import (
    ChaseDraft,
    GapFinding,
    GapFindings,
    PlanStep,
    ProposedPlan,
    ResearchAnswer,
)
from app.packages.preflight.schemas import PreflightFinding, PreflightReport
from app.packages.rfe_response.schemas import (
    ResponseChecklist,
    RfeNotice,
    RfeResponseReport,
)
from app.schemas import (
    AttorneyInfo,
    BeneficiaryInfo,
    ClaimVerification,
    CriterionAssessment,
    EligibilityInfo,
    EvidenceItem,
    EvidenceMatrix,
    ExhibitIndex,
    FinalMeritsAssessment,
    G28Data,
    PassportData,
    ProfileSummary,
    ProfileVerification,
    SourceRef,
    VisaVerdict,
)

# Roots only — nested models (SourceRef inside EvidenceItem, AttorneyInfo
# inside G28Data, ...) are discovered by the recursive walk. Some are listed
# explicitly anyway because they are passed to Gemini directly.
RESPONSE_SCHEMA_MODELS: tuple[type[BaseModel], ...] = (
    # extraction (ExtractionEnvelope data models)
    PassportData,
    G28Data,
    AttorneyInfo,
    BeneficiaryInfo,
    EligibilityInfo,
    # screener
    EvidenceMatrix,
    EvidenceItem,
    SourceRef,
    CriterionAssessment,
    FinalMeritsAssessment,
    ProfileVerification,
    ClaimVerification,
    ProfileSummary,
    VisaVerdict,
    # exhibit index (pure-code artifact, but flatness is lint-enforced so it
    # stays Gemini-safe if a future phase ever hands it to the model)
    ExhibitIndex,
    # preflight (pure-code report contracts; lint-clean so a future doc-type
    # plane that drafts findings via a model inherits a Gemini-safe schema)
    PreflightFinding,
    PreflightReport,
    # rfe-response (RfeNotice on the vision call + ResponseChecklist on the
    # distillation call are handed to Gemini directly; RfeResponseReport is a
    # pure-code artifact kept lint-clean, its nested RfeGround/ChecklistItem
    # reached by the walk)
    RfeNotice,
    ResponseChecklist,
    RfeResponseReport,
    # matter-intake (chase / planner / ask distillation schemas — handed to
    # Gemini directly, so flatness is enforced here)
    GapFindings,
    GapFinding,
    ChaseDraft,
    ProposedPlan,
    PlanStep,
    ResearchAnswer,
)


MODELS = all_models(RESPONSE_SCHEMA_MODELS)


def test_walk_reaches_nested_models() -> None:
    """Sanity: the walk actually recurses (SourceRef via EvidenceItem,
    AttorneyInfo via G28Data) — otherwise the lint tests prove nothing."""
    walked = set(all_models([EvidenceMatrix, G28Data]))
    assert SourceRef in walked
    assert EvidenceItem in walked
    assert AttorneyInfo in walked
    assert EligibilityInfo in walked


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_no_discriminated_unions(model: type[BaseModel]) -> None:
    offenders = discriminator_offenders(model)
    assert not offenders, (
        f"{model.__name__} uses pydantic discriminator on {offenders}; "
        "Gemini response_schema does not support discriminated unions"
    )


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_no_max_items_on_list_of_model_fields(model: type[BaseModel]) -> None:
    offenders = max_items_offenders(model)
    assert not offenders, (
        f"{model.__name__}.{offenders} sets max_length/maxItems on a list of "
        "nested models — Gemini rejects maxItems on lists of objects "
        "(400 INVALID_ARGUMENT); enforce the cap deterministically instead"
    )


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_model_json_schema_serializes(model: type[BaseModel]) -> None:
    assert json_schema_ok(model)
