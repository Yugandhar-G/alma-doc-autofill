"""CLI: agent fan-out authors a candidate package, then a code-owned pipeline
gates it.

    python -m devtools.package_author --brief <path.md> --candidate-id <slug>

Four authoring agents (one per artifact family) run the kernel tool loop with a
budget, each granted ONLY read_exemplar + write_candidate. They DRAFT files into
app/packages/_candidates/<candidate_id>/. Then run_acceptance gates the draft
and a PASS/FAIL verdict is printed and written to ACCEPTANCE.md.

This flow calls live Gemini for the fan-out (make_agent_model). It is a dev-time
tool; it never runs in CI and never touches app/registry.py. See README.md for
the I-864 dogfood.

make_agent_model is re-exported here as a module-level seam so a harness/test
can inject a scripted model without a key (mirrors the screener/matter_intake
pattern).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.kernel.agent import (  # make_agent_model module-level: test seam
    AgentBudget,
    AgentTranscript,
    make_agent_model,
    run_tool_loop,
)
from app.kernel.config import get_settings
from app.kernel.tools.registry import ToolContext
from devtools.package_author import sandbox
from devtools.package_author.acceptance import AcceptanceReport, run_acceptance
from devtools.package_author.prompts import FAMILY_ORDER, family_prompt
from devtools.package_author.tools import build_authoring_registry

logger = logging.getLogger("yunaki.devtools.package_author")

_DEFAULT_BUDGET = 10


def _scaffold(candidate_id: str) -> Path:
    """Ensure the candidate sandbox and the _candidates package marker exist.
    _candidates/__init__.py is needed so the candidate imports as
    app.packages._candidates.<id>; it is gitignored (runtime-only)."""
    root = sandbox.candidate_root(candidate_id)
    root.mkdir(parents=True, exist_ok=True)
    marker = root.parent / "__init__.py"
    if not marker.exists():
        marker.write_text('"""Agent-authored package candidates (runtime sandbox)."""\n', encoding="utf-8")
    return root


async def author_candidate(
    *, brief: str, candidate_id: str, budget: int = _DEFAULT_BUDGET, live: bool = True
) -> list[AgentTranscript]:
    """Run the four authoring agents sequentially. Each gets its family prompt,
    the two authoring tools, and its own transcript. Returns the transcripts for
    logging/auditing. Model comes from make_agent_model (seam)."""
    settings = get_settings()
    registry = build_authoring_registry(candidate_id)
    transcripts: list[AgentTranscript] = []
    for family in FAMILY_ORDER:
        transcript = AgentTranscript()
        ctx = ToolContext(
            settings=settings,
            transcript=transcript,
            emit=lambda _e: None,
            node=f"author.{family}",
        )
        await run_tool_loop(
            model=make_agent_model(settings, live=live),
            task_prompt=family_prompt(family, brief=brief, candidate_id=candidate_id),
            tools=registry,
            budget=AgentBudget(max_tool_calls=budget),
            ctx=ctx,
            live=live,
            trace_name=f"gemini.package_author.{family}",
        )
        logger.info(
            "authoring agent done family=%s tool_calls=%d files=%d",
            family, transcript.tool_calls, len(transcript.seen_refs),
        )
        transcripts.append(transcript)
    return transcripts


def _write_report(candidate_id: str, report: AcceptanceReport) -> Path:
    root = sandbox.candidate_root(candidate_id)
    path = root / "ACCEPTANCE.md"
    path.write_text(report.to_markdown(), encoding="utf-8")
    return path


async def _main_async(args: argparse.Namespace) -> int:
    brief_path = Path(args.brief)
    if not brief_path.is_file():
        print(f"brief not found: {brief_path}", file=sys.stderr)
        return 2
    if not sandbox.is_valid_candidate_id(args.candidate_id):
        print(f"invalid candidate id (slug required): {args.candidate_id!r}", file=sys.stderr)
        return 2
    brief = brief_path.read_text(encoding="utf-8")

    _scaffold(args.candidate_id)
    if not args.skip_authoring:
        await author_candidate(brief=brief, candidate_id=args.candidate_id, budget=args.budget)
    else:
        logger.info("--skip-authoring: gating the existing candidate as-is")

    report = run_acceptance(args.candidate_id, run_pytest=not args.no_pytest)
    print(report.to_markdown())
    dest = _write_report(args.candidate_id, report)
    print(f"\nverdict written to {dest}", file=sys.stderr)
    return 0 if report.passed else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="devtools.package_author")
    parser.add_argument("--brief", required=True, help="Path to the package brief (.md).")
    parser.add_argument("--candidate-id", required=True, help="Sandbox slug (e.g. i864-refresh).")
    parser.add_argument("--budget", type=int, default=_DEFAULT_BUDGET, help="Tool-call budget per agent.")
    parser.add_argument(
        "--skip-authoring", action="store_true",
        help="Skip the live fan-out and only run the acceptance pipeline over an existing candidate.",
    )
    parser.add_argument(
        "--no-pytest", action="store_true",
        help="Skip the full-suite pytest gate (faster iteration; the CLI runs it by default).",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
