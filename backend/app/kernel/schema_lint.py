"""Schema-lint rules for Gemini response_schema safety.

Extracted from tests/test_schema_lint.py so two callers enforce byte-identical
rules: the test suite (over the installed packages' response-schema models) and
the package-author acceptance pipeline (over a candidate package's schemas). If
the rules ever change, both move together — a candidate cannot pass a gate the
shipped models would fail.

Pure and offline (no API calls). The rules, verified against live Gemini:
(a) no discriminated unions anywhere (pydantic ``discriminator``),
(b) no maxItems/max_length on any list-of-BaseModel field — Gemini rejects
    maxItems on lists of nested objects with 400 INVALID_ARGUMENT; caps on
    scalar lists (list[str] etc.) are fine,
(c) the model serializes via model_json_schema() to an object schema.
"""
from __future__ import annotations

import types
import typing

import annotated_types
from pydantic import BaseModel


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


def discriminator_offenders(model: type[BaseModel]) -> list[str]:
    """Field names using a pydantic discriminator (discriminated union)."""
    return [
        name
        for name, field in model.model_fields.items()
        if field.discriminator is not None
    ]


def max_items_offenders(model: type[BaseModel]) -> list[str]:
    """Field names setting max_length/maxItems on a list of nested models."""
    offenders: list[str] = []
    for name, field in model.model_fields.items():
        if not _is_list_of_models(field.annotation):
            continue  # caps on scalar lists (list[str], ...) are fine
        if any(isinstance(meta, annotated_types.MaxLen) for meta in field.metadata):
            offenders.append(name)
    return offenders


def json_schema_ok(model: type[BaseModel]) -> bool:
    """The model serializes to an object JSON schema."""
    schema = model.model_json_schema()
    return isinstance(schema, dict) and schema.get("type", "object") == "object"


def lint_violations(model: type[BaseModel]) -> list[str]:
    """Every rule violation on one model, as human-readable strings. Empty
    means the model is Gemini-response-schema safe."""
    out: list[str] = []
    for name in discriminator_offenders(model):
        out.append(
            f"{model.__name__}.{name}: pydantic discriminator (Gemini "
            "response_schema does not support discriminated unions)"
        )
    for name in max_items_offenders(model):
        out.append(
            f"{model.__name__}.{name}: max_length/maxItems on a list of nested "
            "models (Gemini rejects maxItems on lists of objects; enforce the "
            "cap deterministically instead)"
        )
    if not json_schema_ok(model):
        out.append(f"{model.__name__}: model_json_schema() is not an object schema")
    return out


def lint_all(roots: typing.Iterable[type[BaseModel]]) -> dict[str, list[str]]:
    """Walk from roots and collect violations per model. Empty dict → clean."""
    report: dict[str, list[str]] = {}
    for model in all_models(roots):
        violations = lint_violations(model)
        if violations:
            report[model.__name__] = violations
    return report
