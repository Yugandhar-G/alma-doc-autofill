"""The acceptance pipeline — pure code that gates an agent-authored candidate.

Agent-authored is NOT agent-installed. The fan-out agents only ever wrote files
into a candidate sandbox; this pipeline decides whether that draft is even a
valid package. It NEVER touches app/registry.py — a human adds a passing
candidate to the registry, by hand, after reading this verdict.

Gates (each independent, all reported):
  (a) compile — every candidate .py compiles (py_compile), and the package
      imports in an isolated subprocess.
  (b) package — exports PACKAGE: WorkflowPackage with a validating manifest.
  (c) lint    — its schemas pass the shared Gemini response-schema lint rules.
  (d) eval    — its eval kit runs through the kernel Harness offline, exits 0,
      zero worst-class results.
  (e) pytest  — the full suite is still green (run by the CLI; opt-out in unit
      tests so the acceptance test does not re-enter pytest).

Gates (b)(c)(d) plus the import half of (a) run inside one fresh-interpreter
subprocess (_inspect.py) so a candidate's import-time behavior cannot corrupt
this process.
"""
from __future__ import annotations

import json
import py_compile
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from devtools.package_author import sandbox

_INSPECT_TIMEOUT_S = 120
_PYTEST_TIMEOUT_S = 600


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    reason: str = ""


@dataclass(frozen=True)
class AcceptanceReport:
    candidate_id: str
    gates: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)

    def to_markdown(self) -> str:
        verdict = "PASS ✅" if self.passed else "FAIL ❌"
        lines = [
            f"# Candidate Acceptance — `{self.candidate_id}`",
            "",
            f"**Verdict: {verdict}**",
            "",
            "Agent-authored, code-gated. This candidate is NOT installed. A human "
            "adds a passing candidate to `app/registry.py` by hand.",
            "",
            "| gate | result | reason |",
            "|---|---|---|",
        ]
        for gate in self.gates:
            mark = "PASS" if gate.passed else "FAIL"
            reason = (gate.reason or "").replace("\n", " ").replace("|", "\\|")
            lines.append(f"| {gate.name} | {mark} | {reason} |")
        lines.append("")
        return "\n".join(lines)


def _candidate_py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def gate_compile(root: Path) -> GateResult:
    """(a1) Every candidate .py compiles. py_compile parses without executing —
    a syntax error is caught here with a precise location before any import."""
    files = _candidate_py_files(root)
    if not files:
        return GateResult("compile", False, "candidate directory has no .py files")
    failures: list[str] = []
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            rel = path.relative_to(root)
            failures.append(f"{rel}: {exc.msg.strip().splitlines()[-1]}")
    if failures:
        return GateResult("compile", False, "; ".join(failures))
    return GateResult("compile", True, f"{len(files)} files compiled")


def _run_inspector(candidate_id: str) -> dict:
    """Run _inspect.py in a fresh interpreter from the backend root; parse its
    JSON verdict. A crash or non-JSON output is itself a failure signal."""
    proc = subprocess.run(
        [sys.executable, "-m", "devtools.package_author._inspect", candidate_id],
        cwd=str(sandbox.BACKEND_ROOT),
        capture_output=True,
        text=True,
        timeout=_INSPECT_TIMEOUT_S,
    )
    stdout = proc.stdout.strip()
    try:
        # The verdict is the last JSON line (imports may print warnings above).
        line = [ln for ln in stdout.splitlines() if ln.startswith("{")][-1]
        return json.loads(line)
    except (IndexError, json.JSONDecodeError):
        return {
            "_crashed": True,
            "reason": (proc.stderr.strip() or stdout or "inspector produced no verdict")[-800:],
        }


def gate_pytest() -> GateResult:
    """(e) Full suite still green. Runs from the backend root; the candidate
    lives under app/packages/_candidates/ which pytest does not collect, so this
    proves the candidate's mere presence did not break the shipped suite."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=str(sandbox.BACKEND_ROOT),
        capture_output=True,
        text=True,
        timeout=_PYTEST_TIMEOUT_S,
    )
    tail = (proc.stdout.strip().splitlines() or ["(no output)"])[-1]
    return GateResult("pytest", proc.returncode == 0, tail)


def run_acceptance(candidate_id: str, *, run_pytest: bool = True) -> AcceptanceReport:
    """Run every gate and return the report. Gates are independent — a failed
    compile still reports the downstream gates as failed-with-reason rather than
    silently skipping them, so the verdict table is always complete.

    run_pytest is opt-out so the acceptance unit test does not recursively
    re-enter the pytest process; the CLI always runs it.
    """
    if not sandbox.is_valid_candidate_id(candidate_id):
        raise ValueError(f"invalid candidate id: {candidate_id!r}")
    root = sandbox.candidate_root(candidate_id)
    if not root.is_dir():
        gate = GateResult("compile", False, f"no candidate directory: {root}")
        return AcceptanceReport(candidate_id, (gate,))

    compile_gate = gate_compile(root)

    # The subprocess gates only run if compile passed (importing code that does
    # not parse is pointless); otherwise report them failed for the same reason.
    if compile_gate.passed:
        verdict = _run_inspector(candidate_id)
        if verdict.get("_crashed"):
            reason = f"inspector crashed: {verdict.get('reason', '')}"
            package_gate = GateResult("package", False, reason)
            lint_gate = GateResult("lint", False, reason)
            eval_gate = GateResult("eval", False, reason)
            import_gate = GateResult("import", False, reason)
        else:
            import_gate = GateResult("import", verdict["import"]["ok"], verdict["import"]["reason"])
            package_gate = GateResult("package", verdict["package"]["ok"], verdict["package"]["reason"])
            lint_gate = GateResult("lint", verdict["lint"]["ok"], verdict["lint"]["reason"])
            eval_gate = GateResult("eval", verdict["eval"]["ok"], verdict["eval"].get("reason", ""))
    else:
        skip = "skipped: compile gate failed"
        import_gate = GateResult("import", False, skip)
        package_gate = GateResult("package", False, skip)
        lint_gate = GateResult("lint", False, skip)
        eval_gate = GateResult("eval", False, skip)

    gates = [compile_gate, import_gate, package_gate, lint_gate, eval_gate]
    if run_pytest:
        gates.append(gate_pytest())
    return AcceptanceReport(candidate_id, tuple(gates))
