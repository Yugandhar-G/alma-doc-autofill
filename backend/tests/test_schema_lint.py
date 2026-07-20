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
"""
import types
import typing

import annotated_types
import pytest
from pydantic import BaseModel

from app.packages.preflight.schemas import PreflightFinding, PreflightReport
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
)


def _nested_models(annotation: object) -> list[type[BaseModel]]:
    """Every BaseModel subclass reachable inside a type annotation
    (Optional/Union, list/dict/tuple, Annotated — all unwrapped)."""
    found: list[type[BaseModel]] = []
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        found.append(annotation)
    for arg in typing.get_args(annotation):
        found.extend(_nested_models(arg))
    return found


def _is_list_of_models(annotation: object) -> bool:
    """True when the annotation is (or contains, via Optional/Union) a
    list/tuple/set whose element type reaches a BaseModel."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return any(_is_list_of_models(arg) for arg in typing.get_args(annotation))
    if origin in (list, tuple, set, frozenset):
        return any(_nested_models(arg) for arg in typing.get_args(annotation))
    return False


def all_models(roots: typing.Iterable[type[BaseModel]]) -> list[type[BaseModel]]:
    """Recursive walk over the model graph with a visited set."""
    visited: dict[type[BaseModel], None] = {}  # dict → deterministic order
    stack = list(roots)
    while stack:
        model = stack.pop(0)
        if model in visited:
            continue
        visited[model] = None
        for field in model.model_fields.values():
            stack.extend(_nested_models(field.annotation))
    return list(visited)


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
    offenders = [
        name
        for name, field in model.model_fields.items()
        if field.discriminator is not None
    ]
    assert not offenders, (
        f"{model.__name__} uses pydantic discriminator on {offenders}; "
        "Gemini response_schema does not support discriminated unions"
    )


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_no_max_items_on_list_of_model_fields(model: type[BaseModel]) -> None:
    offenders = []
    for name, field in model.model_fields.items():
        if not _is_list_of_models(field.annotation):
            continue  # caps on scalar lists (list[str], ...) are fine
        if any(isinstance(meta, annotated_types.MaxLen) for meta in field.metadata):
            offenders.append(name)
    assert not offenders, (
        f"{model.__name__}.{offenders} sets max_length/maxItems on a list of "
        "nested models — Gemini rejects maxItems on lists of objects "
        "(400 INVALID_ARGUMENT); enforce the cap deterministically instead"
    )


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_model_json_schema_serializes(model: type[BaseModel]) -> None:
    schema = model.model_json_schema()
    assert isinstance(schema, dict) and schema.get("type", "object") == "object"
