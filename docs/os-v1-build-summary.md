# Yunaki Agentic OS v1 — Build Summary

**Built:** 2026-07-19 → 2026-07-20 (one session, Fable orchestrating a fleet of Opus subagents under disjoint file ownership).
**Result:** the two point tools (doc-autofill, O-1A/EB-1A screener) are now a workflow OS. Backend **564 passed / 28 skipped**; frontend build/lint/9-tests green; desktop everything verified except the Rust compile (no toolchain on the build machine — `cd desktop/src-tauri && cargo check`). 18 commits, `233f08b`…`68df57d`.

## The seven OS layers, now in code
| Layer | Where |
|---|---|
| Kernel (deterministic graph runtime) | `app/kernel/runtime/` (RunManager, checkpoints, runner, scheduler, WorkflowService) |
| Drivers (guardrailed tools) | `app/kernel/tools/` (registry allow-list, SSRF guards, web + corpus tools); `app/forms/fill.py` (native PDF fill — the OS population path); Playwright legacy only |
| Audit (overrules the model) | `app/kernel/audit/` + `app/kernel/schema_lint.py`; per-package citation policy in `screener/citations.py`; evalkit worst-class gate |
| Processes (matter workflows) | six installed packages via `app/registry.py`; graphs checkpoint + interrupt + resume across restart |
| Shell (human work queue) | `frontend/src/app/(shell)/` process table, run views, InterruptPanel, inbox |
| Filesystem (firm memory) | `app/kernel/store/` (firm-scoped matter store) + `app/kernel/memory/` (citable, audited recall) |
| Scheduler / IPC | `app/kernel/runtime/scheduler.py` (per-firm cap) + first-class Interrupt rows = the inbox |

## Agent discipline (the moat, enforced in code)
- Loop on **deepagents** with a **HarnessProfile** (no filesystem/execute/subagent builtins) and **GrantEnforcementMiddleware** — a non-granted tool call is refused at execution, not just hidden. Regression-tested per agent.
- **Code owns every path, budget, and audit.** LLM picks tools within grants inside a node; it never picks a graph edge. Structured calls stay on the direct Gemini path (no langchain) so `response_schema` discipline holds.
- **Transcript audit:** an agent's claim citing a source it never opened (`seen_urls`/`seen_refs`) is stripped; deep agents investigate firm data through TenantScope-enforced corpus tools.
- **Citation audit + overclaim gate:** uncited positive verdicts downgrade; the eval harness exits nonzero on any fabricated/overclaim result — kernel-hardwired, not per-package opt-in.

## Product surfaces
- **Packet Pre-Flight (the wedge):** deterministic pre-filing consistency audit — identity diffs across forms, form-edition currency (live off the 23-profile verified forms registry), translation + evidence completeness, I-864 income math. Zero-LLM; its own offline eval with a clean-packet fabrication bait.
- **Document chase agent, matter planner, ask-the-matter:** firm-data deep agents; chase drafts (never sends), planner queues (never executes), ask answers with audited citations or says it can't.
- **Screener + NIW + exhibit index:** three Dhanasar prongs installed as data (registry-as-data proof #2); pure-code exhibit map from post-audit citations.
- **RFE assembler:** notice → deadline math → cited response checklist → records `MemoryRecord(kind="rfe")` that future Pre-Flight runs recall.
- **Package-author devtool:** agents draft a vertical into a sandbox; a pure-code acceptance pipeline (compile, isolated import, contract, lint, zero-overclaim eval, pytest) gates it. Agent-authored ≠ agent-installed.

## Form factor
Native Mac/Windows desktop app (Tauri 2 + PyInstaller FastAPI sidecar, per-launch bearer token, `window.__YUNAKI_API__` injection). Firm sign-in syncs matters/runs/interrupts/memory via Supabase; **no-account mode is fully local with zero setup**. All agent work + document processing runs on the attorney's machine.

## Honest gaps / follow-ups
- Rust/Tauri compile unverified (no toolchain here) — one documented command.
- Screener session-create not rate-limited (legacy Principal-less surface).
- RLS SQL structural-tested only (no live Supabase in CI).
- Package-run parked-review payload session-scoped; per-node stage telemetry coarse; frontend TS mirrors of `exhibit_index` deferred.
- macOS/Windows signing certs + Tauri updater keys are E2 documentation, not provisioned.

Full per-phase delegation record (every subagent prompt + every coordinator correction) is in `docs/agent-usage-log.md`.
