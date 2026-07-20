"""The two code-owned tools an authoring agent is granted: read_exemplar and
write_candidate. Nothing else — the registry these build is the whole surface,
and GrantEnforcementMiddleware refuses any other name (write_file, execute, …)
at the execution layer.

Both are per-run: the run's candidate_id is baked into the tools at build time
(closure), never taken from model arguments, so the model cannot redirect a
write to another candidate. Each tool records what it touched into
transcript.seen_refs — the deterministic ground truth an author-run audit reads,
exactly as the corpus/web tools grow seen_refs / seen_urls.
"""
from __future__ import annotations

from google.genai import types as genai_types

from app.kernel.tools.registry import ToolContext, ToolRegistry, ToolSpec
from devtools.package_author import sandbox

# Reads are capped before re-entering the model context (an exemplar cannot
# blow the prompt budget); writes are size-capped (a candidate file is source,
# not a data dump).
_MAX_READ_CHARS = 24_000
_MAX_WRITE_BYTES = 96 * 1024

READ_REFUSED = "READ_REFUSED"
WRITE_REFUSED = "WRITE_REFUSED"


def _cap_read(text: str) -> str:
    if len(text) <= _MAX_READ_CHARS:
        return text
    return text[:_MAX_READ_CHARS] + "\n…[truncated]"


def _record_ref(transcript, ref: str) -> None:
    if ref and ref not in transcript.seen_refs:
        transcript.seen_refs.append(ref)


def build_authoring_tools(candidate_id: str) -> tuple[ToolSpec, ToolSpec]:
    """The (read_exemplar, write_candidate) pair for one authoring run.

    Raises ValueError if candidate_id is not a valid slug — a bad id is a
    caller bug, caught before any agent runs, never silently at write time."""
    if not sandbox.is_valid_candidate_id(candidate_id):
        raise ValueError(f"invalid candidate id: {candidate_id!r}")

    async def _run_read_exemplar(args: dict, ctx: ToolContext) -> str:
        path = str(args.get("path", ""))
        ctx.emit({"type": "tool_call", "node": ctx.node, "tool": "read_exemplar", "path": path})
        resolved = sandbox.resolve_read_path(path)
        if resolved is None:
            ctx.transcript.log.append(f"read_exemplar({path!r}) -> REFUSED")
            ctx.emit({"type": "tool_result", "node": ctx.node, "tool": "read_exemplar", "status": "refused"})
            return (
                f"{READ_REFUSED}: reads are limited to app/packages/ and "
                "app/kernel/package.py. That path is outside the allow-list."
            )
        if not resolved.is_file():
            ctx.transcript.log.append(f"read_exemplar({path!r}) -> not found")
            return f"{READ_REFUSED}: no such file under the allow-list: {path}"
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            ctx.transcript.log.append(f"read_exemplar({path!r}) -> {type(exc).__name__}")
            return f"{READ_REFUSED}: could not read that file ({type(exc).__name__})."
        _record_ref(ctx.transcript, path)
        ctx.transcript.log.append(f"read_exemplar({path!r}) -> {len(text)} chars")
        ctx.emit({"type": "tool_result", "node": ctx.node, "tool": "read_exemplar", "chars": len(text)})
        return _cap_read(text)

    async def _run_write_candidate(args: dict, ctx: ToolContext) -> str:
        relpath = str(args.get("relpath", ""))
        content = args.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        ctx.emit({"type": "tool_call", "node": ctx.node, "tool": "write_candidate", "relpath": relpath})
        resolved = sandbox.resolve_write_path(candidate_id, relpath)
        if resolved is None:
            ctx.transcript.log.append(f"write_candidate({relpath!r}) -> REFUSED")
            ctx.emit({"type": "tool_result", "node": ctx.node, "tool": "write_candidate", "status": "refused"})
            return (
                f"{WRITE_REFUSED}: writes are limited to this run's candidate "
                "sandbox. Absolute paths and '..' escapes are refused. Use a "
                "relative path inside the candidate package."
            )
        encoded = content.encode("utf-8")
        if len(encoded) > _MAX_WRITE_BYTES:
            ctx.transcript.log.append(f"write_candidate({relpath!r}) -> too big {len(encoded)}B")
            return (
                f"{WRITE_REFUSED}: file exceeds {_MAX_WRITE_BYTES} bytes "
                f"({len(encoded)}). Split it into smaller modules."
            )
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
        except OSError as exc:
            ctx.transcript.log.append(f"write_candidate({relpath!r}) -> {type(exc).__name__}")
            return f"{WRITE_REFUSED}: write failed ({type(exc).__name__})."
        _record_ref(ctx.transcript, relpath)
        ctx.transcript.log.append(f"write_candidate({relpath!r}) -> {len(encoded)} bytes")
        ctx.emit({"type": "tool_result", "node": ctx.node, "tool": "write_candidate", "bytes": len(encoded)})
        return f"WROTE: {relpath} ({len(encoded)} bytes)"

    read_spec = ToolSpec(
        name="read_exemplar",
        description=(
            "Read a reference source file to study the shipped package pattern "
            "before you write. Allowed paths: anything under 'app/packages/' "
            "(study 'app/packages/preflight/...' — the exemplar) and the file "
            "'app/kernel/package.py' (the WorkflowPackage contract). Returns the "
            "file text (capped). Any other path is refused."
        ),
        parameters=genai_types.Schema(
            type=genai_types.Type.OBJECT,
            properties={
                "path": genai_types.Schema(
                    type=genai_types.Type.STRING,
                    description="Repo-relative path, e.g. 'app/packages/preflight/schemas.py'.",
                )
            },
            required=["path"],
        ),
        run=_run_read_exemplar,
    )
    write_spec = ToolSpec(
        name="write_candidate",
        description=(
            "Write one source file into THIS run's candidate package sandbox. "
            "The path is relative to the candidate package root, e.g. "
            "'schemas.py' or 'eval/personas.py'. You cannot write anywhere else "
            "— absolute paths and '..' are refused. Call once per file."
        ),
        parameters=genai_types.Schema(
            type=genai_types.Type.OBJECT,
            properties={
                "relpath": genai_types.Schema(
                    type=genai_types.Type.STRING,
                    description="Path inside the candidate package, e.g. 'graph.py'.",
                ),
                "content": genai_types.Schema(
                    type=genai_types.Type.STRING,
                    description="Full UTF-8 source text of the file.",
                ),
            },
            required=["relpath", "content"],
        ),
        run=_run_write_candidate,
    )
    return read_spec, write_spec


def build_authoring_registry(candidate_id: str) -> ToolRegistry:
    """The complete tool surface an authoring agent gets: exactly the two
    code-owned tools. Any other name → UNKNOWN_TOOL at dispatch, and any
    deepagents builtin → refused by GrantEnforcementMiddleware."""
    return ToolRegistry(build_authoring_tools(candidate_id))
