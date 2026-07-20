"""Offline tests for the agent-authored packages devtool.

No live Gemini: the fan-out is exercised with a scripted model, and the
acceptance pipeline runs over fixture candidates the TEST writes (never an
agent). The sandbox is the product, so it is hammered adversarially — a path
escape must be impossible by construction, not merely unlikely.
"""
from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from app.kernel.agent import AgentBudget, AgentTranscript, run_tool_loop
from app.kernel.tools.registry import ToolContext
from devtools.package_author import sandbox
from devtools.package_author.acceptance import run_acceptance
from devtools.package_author.tools import build_authoring_registry, build_authoring_tools


# --------------------------------------------------------------------------- #
# Scripted model (same shape as tests/test_screener_agent.py)                 #
# --------------------------------------------------------------------------- #
class ScriptedChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _tool_call_msg(*calls):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{i}"}
            for i, (name, args) in enumerate(calls)
        ],
    )


def _ctx(transcript: AgentTranscript) -> ToolContext:
    return ToolContext(
        settings=SimpleNamespace(), transcript=transcript, emit=lambda _e: None, node="t"
    )


# --------------------------------------------------------------------------- #
# Sandbox unit tests — pure path discipline, no filesystem, no loop           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "relpath",
    [
        "../../registry.py",         # the structural-escape target
        "../preflight/graph.py",     # sibling shipped package
        "../../../etc/passwd",       # out of the repo
        "/etc/passwd",               # absolute
        "/Users/x/app/registry.py",  # absolute inside-ish
        "..",                        # the parent itself
        "foo/../../bar.py",          # mid-path traversal escaping root
        "",                          # empty
    ],
)
def test_resolve_write_path_refuses_escapes(relpath):
    assert sandbox.resolve_write_path("cand", relpath) is None


@pytest.mark.parametrize("relpath", ["schemas.py", "eval/personas.py", "knowledge/reqs.py"])
def test_resolve_write_path_allows_inside_sandbox(relpath):
    resolved = sandbox.resolve_write_path("cand", relpath)
    assert resolved is not None
    assert resolved.is_relative_to(sandbox.candidate_root("cand"))


@pytest.mark.parametrize(
    "path,allowed",
    [
        ("app/packages/preflight/schemas.py", True),
        ("app/packages/preflight/graph.py", True),
        ("app/kernel/package.py", True),
        ("app/registry.py", False),          # NOT the allow-listed package.py
        ("app/kernel/agent.py", False),       # kernel internals off-limits
        ("app/config.py", False),
        ("../../../etc/passwd", False),
        ("/etc/passwd", False),
        ("app/packages", False),              # the dir itself, not a file
    ],
)
def test_resolve_read_path_allow_list(path, allowed):
    assert (sandbox.resolve_read_path(path) is not None) is allowed


@pytest.mark.parametrize("bad", ["../evil", "a/b", "Cand Space", "", "/abs", ".."])
def test_invalid_candidate_ids_rejected(bad):
    assert not sandbox.is_valid_candidate_id(bad)
    with pytest.raises(ValueError):
        sandbox.candidate_root(bad)


# --------------------------------------------------------------------------- #
# Tools through the kernel loop — the escape/refusal regressions             #
# --------------------------------------------------------------------------- #
async def test_write_outside_sandbox_is_refused_zero_writes():
    """The structural-escape regression: an agent scripting a write to
    ../../registry.py is refused, nothing is written outside the sandbox, and
    the ref is never recorded."""
    registry_py = sandbox.BACKEND_ROOT / "app" / "registry.py"
    before = registry_py.read_text(encoding="utf-8")

    transcript = AgentTranscript()
    await run_tool_loop(
        model=ScriptedChatModel(
            responses=[
                _tool_call_msg(
                    ("write_candidate", {"relpath": "../../registry.py", "content": "PWNED = True"})
                ),
                AIMessage(content="done."),
            ]
        ),
        task_prompt="author",
        tools=build_authoring_registry("escape_test"),
        budget=AgentBudget(max_tool_calls=5),
        ctx=_ctx(transcript),
    )

    assert registry_py.read_text(encoding="utf-8") == before  # untouched
    assert "PWNED" not in registry_py.read_text(encoding="utf-8")
    assert transcript.seen_refs == []                          # refused writes leave no ref
    # The tool WAS dispatched (it is granted) but refused inside — proving the
    # refusal is structural, not a missing grant.
    assert transcript.tool_calls == 1
    assert not sandbox.candidate_root("escape_test").exists()  # no sandbox materialized


async def test_read_outside_allow_list_is_refused():
    read_spec, _ = build_authoring_tools("cand")
    transcript = AgentTranscript()
    ctx = _ctx(transcript)
    # A read of a non-allow-listed file returns READ_REFUSED and records nothing.
    result = await read_spec.run({"path": "app/registry.py"}, ctx)
    assert result.startswith("READ_REFUSED")
    assert transcript.seen_refs == []
    # An allow-listed exemplar reads and records its ref.
    ok = await read_spec.run({"path": "app/packages/preflight/schemas.py"}, ctx)
    assert "READ_REFUSED" not in ok and "PreflightReport" in ok
    assert transcript.seen_refs == ["app/packages/preflight/schemas.py"]


@pytest.mark.parametrize("builtin", ["write_file", "execute", "read_file"])
async def test_non_granted_tool_is_blocked(builtin):
    """Grant-block regression: an authoring agent's registry grants only the
    two authoring tools; any deepagents builtin is refused at the execution
    layer (UNKNOWN_TOOL), never dispatched."""
    transcript = AgentTranscript()
    await run_tool_loop(
        model=ScriptedChatModel(
            responses=[
                _tool_call_msg((builtin, {"file_path": "/tmp/x", "content": "y"})),
                AIMessage(content="done."),
            ]
        ),
        task_prompt="author",
        tools=build_authoring_registry("cand"),
        budget=AgentBudget(max_tool_calls=5),
        ctx=_ctx(transcript),
    )
    assert transcript.tool_calls == 0  # nothing granted was ever dispatched


# --------------------------------------------------------------------------- #
# Acceptance pipeline — over fixture candidates the TEST writes               #
# --------------------------------------------------------------------------- #
def _valid_files() -> dict[str, str]:
    """A minimal but genuinely valid candidate package (relative imports work
    because it is imported as app.packages._candidates.<id>)."""
    return {
        "__init__.py": "",
        "schemas.py": (
            "from pydantic import BaseModel, Field\n\n\n"
            "class WidgetFinding(BaseModel):\n"
            "    check_id: str\n"
            "    ok: bool = True\n\n\n"
            "class WidgetReport(BaseModel):\n"
            "    findings: list[WidgetFinding] = Field(default_factory=list)\n"
            "    ok: bool = True\n"
        ),
        "state.py": (
            "from pydantic import BaseModel\n\n"
            "from .schemas import WidgetReport\n\n\n"
            "class WidgetState(BaseModel):\n"
            "    run_id: str\n"
            "    report: WidgetReport | None = None\n"
        ),
        "graph.py": (
            "from langgraph.graph import END, START, StateGraph\n\n"
            "from .state import WidgetState\n\n\n"
            "async def run_node(state: WidgetState) -> dict:\n"
            "    return {}\n\n\n"
            "def build_graph(checkpointer=None):\n"
            "    graph = StateGraph(WidgetState)\n"
            "    graph.add_node('run', run_node)\n"
            "    graph.add_edge(START, 'run')\n"
            "    graph.add_edge('run', END)\n"
            "    return graph.compile(checkpointer=checkpointer)\n"
        ),
        "eval.py": (
            "from app.kernel.evalkit import Harness\n\n\n"
            "async def _run_one(persona):\n"
            "    return {'persona': persona, 'buckets': {'correct': ['x'], 'fabricated': []}}\n\n\n"
            "def _classes_of(result):\n"
            "    return {k for k, v in result.get('buckets', {}).items() if v}\n\n\n"
            "def _render(results):\n"
            "    return 'ok\\n'\n\n\n"
            "def _gate(results):\n"
            "    return 0\n\n\n"
            "def build_harness():\n"
            "    return Harness(\n"
            "        personas=['clean'],\n"
            "        run_one=_run_one,\n"
            "        classes_of=_classes_of,\n"
            "        render=_render,\n"
            "        gate=_gate,\n"
            "        worst_class='fabricated',\n"
            "    )\n"
        ),
        "package.py": (
            "from app.kernel.package import PackageManifest, StageSpec, WorkflowPackage\n\n"
            "from .eval import build_harness\n"
            "from .graph import build_graph\n"
            "from .state import WidgetState\n\n"
            "PACKAGE = WorkflowPackage(\n"
            "    manifest=PackageManifest(\n"
            "        package_id='cand_valid',\n"
            "        version='0.1.0',\n"
            "        title='Widget Check',\n"
            "        description='fixture candidate',\n"
            "        matter_types=('immigration',),\n"
            "        stages=(StageSpec(id='run', label='Run', nodes=('run',)),),\n"
            "    ),\n"
            "    state_model=WidgetState,\n"
            "    build_graph=build_graph,\n"
            "    eval_kit=build_harness,\n"
            ")\n"
        ),
    }


def _write_candidate(candidate_id: str, files: dict[str, str]) -> None:
    root = sandbox.candidate_root(candidate_id)
    # Ensure the _candidates package marker exists so the candidate imports.
    marker = root.parent / "__init__.py"
    if not marker.exists():
        marker.write_text('"""candidates sandbox."""\n', encoding="utf-8")
    for relpath, content in files.items():
        dest = root / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


@pytest.fixture
def make_candidate():
    created: list[str] = []

    def _make(candidate_id: str, files: dict[str, str]) -> str:
        _write_candidate(candidate_id, files)
        created.append(candidate_id)
        return candidate_id

    yield _make

    for candidate_id in created:
        shutil.rmtree(sandbox.candidate_root(candidate_id), ignore_errors=True)


def test_acceptance_passes_minimal_valid_candidate(make_candidate):
    make_candidate("cand_valid", _valid_files())
    report = run_acceptance("cand_valid", run_pytest=False)
    reasons = {g.name: g.reason for g in report.gates}
    assert report.passed, reasons
    assert {g.name for g in report.gates} == {"compile", "import", "package", "lint", "eval"}


def _with_syntax_error() -> dict[str, str]:
    files = _valid_files()
    files["schemas.py"] = "def broken(:\n    pass\n"
    return files


def _without_package() -> dict[str, str]:
    files = _valid_files()
    files["package.py"] = "X = 1  # no PACKAGE exported\n"
    return files


def _with_lint_violation() -> dict[str, str]:
    files = _valid_files()
    files["schemas.py"] = (
        "from typing import Annotated\n\n"
        "from annotated_types import MaxLen\n"
        "from pydantic import BaseModel, Field\n\n\n"
        "class WidgetFinding(BaseModel):\n"
        "    check_id: str\n\n\n"
        "class WidgetReport(BaseModel):\n"
        "    # maxItems on a list of nested models — the lint rule Gemini needs.\n"
        "    findings: Annotated[list[WidgetFinding], MaxLen(5)] = Field(default_factory=list)\n"
    )
    return files


@pytest.mark.parametrize(
    "candidate_id,files,failing_gate",
    [
        ("cand_syntax", _with_syntax_error(), "compile"),
        ("cand_nopackage", _without_package(), "package"),
        ("cand_badlint", _with_lint_violation(), "lint"),
    ],
)
def test_acceptance_fails_broken_candidate(make_candidate, candidate_id, files, failing_gate):
    make_candidate(candidate_id, files)
    report = run_acceptance(candidate_id, run_pytest=False)
    assert not report.passed
    gate = next(g for g in report.gates if g.name == failing_gate)
    assert not gate.passed and gate.reason
    # Gate independence: everything AFTER the failing gate is also reported.
    assert "FAIL" in report.to_markdown()
