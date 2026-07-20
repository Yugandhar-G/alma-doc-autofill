"""Candidate inspector — runs in a FRESH interpreter (subprocess) so importing
an agent-authored package, with whatever import-time side effects it carries,
never pollutes or crashes the parent acceptance process.

Invoked as:  python -m devtools.package_author._inspect <candidate_id>
from the backend root. Emits exactly one JSON object on stdout describing the
import / package / lint / eval gates. All failures are captured into the JSON
(reasons), never raised — the parent reads the verdict, it does not parse a
traceback.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import sys
import traceback
from typing import Any

from pydantic import BaseModel

from app.kernel.evalkit import HARNESS_ERROR_KEY, Harness
from app.kernel.package import WorkflowPackage
from app.kernel.schema_lint import lint_all

_BASE = "app.packages._candidates"


def _schema_roots(package: WorkflowPackage, candidate_id: str) -> list[type[BaseModel]]:
    """Roots for the lint walk: the package state model plus every BaseModel
    DEFINED in the candidate's own schemas module (if it has one). Nested
    models are discovered by the recursive walk, so listing roots is enough."""
    roots: list[type[BaseModel]] = []
    state_model = getattr(package, "state_model", None)
    if isinstance(state_model, type) and issubclass(state_model, BaseModel):
        roots.append(state_model)
    schemas_name = f"{_BASE}.{candidate_id}.schemas"
    try:
        schemas_mod = importlib.import_module(schemas_name)
    except ModuleNotFoundError:
        return roots
    for obj in vars(schemas_mod).values():
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseModel)
            and obj is not BaseModel
            and obj.__module__ == schemas_name
        ):
            roots.append(obj)
    return roots


async def _run_eval(package: WorkflowPackage) -> dict[str, Any]:
    """Run the candidate's eval kit through the kernel Harness, offline.

    Contract: PACKAGE.eval_kit is a zero-arg callable returning a Harness. The
    gate passes only when the harness exit code is 0 AND no result carries the
    package's worst class (or an isolated harness error)."""
    eval_kit = getattr(package, "eval_kit", None)
    if eval_kit is None:
        return {"ok": False, "reason": "PACKAGE.eval_kit is None (no eval kit to run)"}
    if not callable(eval_kit):
        return {"ok": False, "reason": "PACKAGE.eval_kit must be a zero-arg callable returning a Harness"}
    try:
        harness = eval_kit()
    except Exception as exc:  # noqa: BLE001 — verdict, not a crash
        return {"ok": False, "reason": f"eval_kit() raised {type(exc).__name__}: {exc}"}
    if inspect.isawaitable(harness):
        harness = await harness
    if not isinstance(harness, Harness):
        return {"ok": False, "reason": f"eval_kit() returned {type(harness).__name__}, not a kernel Harness"}
    try:
        results = await harness.run()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"harness.run() raised {type(exc).__name__}: {exc}"}
    code = harness.exit_code(results)
    worst = harness.worst_class
    worst_hits = sum(1 for r in results if worst in set(harness.classes_of(r)))
    errors = sum(1 for r in results if HARNESS_ERROR_KEY in r)
    ok = code == 0 and worst_hits == 0 and errors == 0
    reason = "" if ok else (
        f"eval exit={code}, worst_class '{worst}' hits={worst_hits}, "
        f"isolated_errors={errors}"
    )
    return {
        "ok": ok,
        "reason": reason,
        "exit_code": code,
        "worst_class": worst,
        "worst_hits": worst_hits,
        "personas": len(results),
    }


def inspect_candidate(candidate_id: str) -> dict[str, Any]:
    verdict: dict[str, Any] = {
        "import": {"ok": False, "reason": ""},
        "package": {"ok": False, "reason": ""},
        "lint": {"ok": False, "reason": ""},
        "eval": {"ok": False, "reason": "not run (earlier gate failed)"},
    }

    # (a2) import the candidate package in this fresh interpreter.
    try:
        pkg_mod = importlib.import_module(f"{_BASE}.{candidate_id}.package")
    except Exception as exc:  # noqa: BLE001
        verdict["import"]["reason"] = (
            f"import failed: {type(exc).__name__}: {exc}\n"
            + "".join(traceback.format_exception_only(type(exc), exc)).strip()
        )
        return verdict
    verdict["import"]["ok"] = True

    # (b) exports PACKAGE: WorkflowPackage, manifest validates.
    package = getattr(pkg_mod, "PACKAGE", None)
    if package is None:
        verdict["package"]["reason"] = "module has no top-level PACKAGE"
        return verdict
    if not isinstance(package, WorkflowPackage):
        verdict["package"]["reason"] = f"PACKAGE is {type(package).__name__}, not WorkflowPackage"
        return verdict
    try:
        summary = package.manifest.summary()
        assert summary["package_id"], "manifest.package_id is empty"
        assert summary["version"], "manifest.version is empty"
        assert summary["title"], "manifest.title is empty"
        assert callable(package.build_graph), "build_graph is not callable"
        assert isinstance(package.state_model, type) and issubclass(
            package.state_model, BaseModel
        ), "state_model is not a pydantic model"
    except Exception as exc:  # noqa: BLE001
        verdict["package"]["reason"] = f"manifest validation failed: {exc}"
        return verdict
    verdict["package"]["ok"] = True

    # (c) schemas pass the shared lint rules.
    roots = _schema_roots(package, candidate_id)
    if not roots:
        verdict["lint"]["reason"] = "no schema models found (state_model + schemas.py)"
        return verdict
    violations = lint_all(roots)
    if violations:
        flat = "; ".join(f"{m}: {', '.join(v)}" for m, v in violations.items())
        verdict["lint"]["reason"] = f"schema-lint violations: {flat}"
        return verdict
    verdict["lint"]["ok"] = True
    verdict["lint"]["models"] = len(roots)

    # (d) eval kit runs offline, exits 0, zero worst-class.
    verdict["eval"] = asyncio.run(_run_eval(package))
    return verdict


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: _inspect <candidate_id>"}))
        return 2
    verdict = inspect_candidate(sys.argv[1])
    print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
