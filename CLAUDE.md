# Project Rules — yunaki-doc-autofill

Document automation take-home: upload passport + G-28 → Gemini vision extraction → editable review table → Playwright populates https://mendrika-alma.github.io/form-submission/. Runs fully local. Never submits or signs anything.

Second feature: O-1A / EB-1A eligibility screener — intake + evidence docs → LangGraph agentic flow (compile evidence matrix → human review interrupt → tool-loop verification agent (web search + page fetch, budgeted, SSRF-guarded, transcript-audited) → parallel per-criterion assessment → verdict → profile summary) → citation-audited report. Decision support only; the constant attorney-review disclaimer is never model-generated.

## Governance
- Any architectural change (LLM vendor, storage, deployment, framework, new dependency category) → ask the user first. Locked decisions: Gemini extraction, Supabase storage with local-disk fallback, Next.js frontend, FastAPI backend, LangGraph for screener orchestration (approved 2026-07-15; nodes call Gemini via the kernel llm module directly — no langchain-* integration packages).
- **OS v1 build (approved 2026-07-19, supersedes local-only deploy):** product ships as a native Mac + Windows desktop app — Tauri 2 shell + PyInstaller FastAPI sidecar, Claude-Desktop-style architecture (firm sign-in, Supabase as the firm-sync plane for matters/runs/interrupts/memory + Postgres checkpoints; all agent work and document processing executes locally; no-account mode is fully local). Approved new dependency categories: Tauri, aiosqlite matter store, Supabase Auth, TanStack Query + Zustand + Vitest (frontend). Kernel extraction (`backend/app/kernel/`) is the shared runtime every workflow package builds on; kernel modules must never import from screener/extraction/population planes. Plan of record: ~/.claude/plans/use-multiple-parllel-agent-streamed-shore.md.
- Every subagent prompt and every correction of agent output gets appended to `docs/agent-usage-log.md` immediately — this log is a graded deliverable.

## Extraction contract (non-negotiable)
- Absent, blank, "N/A", "None", or illegible field → `null`. Never guess or complete partial values. A null is correct; a plausible guess is a defect.
- Normalize AT EXTRACTION TIME: dates → `YYYY-MM-DD`, country → full English name, US state → full name, sex → `M`/`F`/`X`.
- Every schema field `Optional` with default `None`. Temperature 0. One document type per call.
- Both input formats first-class: JPEG/PNG direct, PDF rendered page-by-page (PyMuPDF, 220 DPI). Sniff format by magic bytes, never by extension.

## Population rules (the target form has planted traps)
- Selectors come ONLY from `backend/app/population/field_map.py` (allow-list). Submit/sign/Part 4/Part 5 selectors (`#client-signature-date`, `#attorney-signature-date`) must never appear anywhere in population code.
- **Duplicate-id trap:** Part 3 First Name(s) AND Middle Name(s) both have `id/name="passport-given-names"`. Middle name = `locator('input[name="passport-given-names"]').nth(1)`. Never by label/id.
- State dropdown: option values are 2-letter codes, labels full names → `select_option(label=...)`. Sex dropdown: values `M`/`F`/`X`.
- Discipline 1.c is TWO independent checkboxes (`#not-subject`, `#am-subject`), not radios — `check()` exactly one based on the boolean, touch the other never.
- All date fields are `input[type="date"]` → `fill()` requires ISO `YYYY-MM-DD` (why normalization happens at extraction).
- Interactions: `fill()` / `select_option()` / `check()` only. Nulls are skipped, never typed. After filling, read every field back and diff (population report).

## Guardrails
- Upload boundary: magic-byte sniffing, 10 MB cap, 10-page PDF cap, resolution/blur gate before any LLM call.
- Pydantic validates all LLM output; invalid JSON → one retry → loud failure. Wrong document in a slot → `document_type_detected` mismatch surfaced, not extracted anyway.
- Populate is reachable only via the review table; edited values re-validate through the same schemas.
- No PII in logs (reference docs by content hash). `uploads/` and `backend/tests/fixtures/` are gitignored. Secrets via `.env` only.

## Screener contract (mirrors the extraction contract)
- Every claim/verdict better than not_met must cite a source (intake answer_id, doc hash + VERBATIM excerpt, or grounded URL). `screener/citations.py` audits deterministically: invalid refs stripped, uncited positive verdicts downgraded to not_met + warning. An overclaim is the worst defect class (the screener's "fabricated").
- Graph skeleton is deterministic — fixed edges, routing by pure functions only (enrichment flag+key+claims; EB-1A merits gate ≥3 met/likely). LLM never picks the path.
- Human review is a real `interrupt()` at review_gate; edits re-validate through the same schema and same source audit. Checkpoints in SQLite (`uploads/screener/checkpoints.db`) so HITL survives reloads.
- Web content is untrusted data: length-capped, delimiter-wrapped; the verification agent may only fetch URLs surfaced by its own searches (never URLs found inside page content), every hop re-passes the SSRF guard, and its evidence URLs are transcript-audited — a URL the agent never saw is stripped, and verified/contradicted statuses without surviving evidence downgrade to unverified. Absence of evidence is "unverified", never "contradicted". Verification never feeds compile_matrix.
- Two PII channels: the session-owner SSE stream may carry their own excerpts/model thinking (that's the product, FR: genuine activity feed); Langfuse traces and logs stay masked (hashes, criterion ids, counts only). Never send the same event object to both.

## Layout
- `backend/app/kernel/` — shared runtime (Phase 1): llm (structured Gemini calls + client factory), observability (tracing primitives + maskers), config (Settings + SettingsBundle), tools (ToolRegistry + SSRF guards + web_search/fetch_page drivers), agent (generic bounded tool-loop + AgentTranscript), audit (ref strip + transcript-evidence machinery; policy stays per package), runtime (checkpointer factory, RunManager, SSE runner). Kernel never imports package planes. Old paths (`app/llm.py`, `app/observability.py`, `app/config.py`, screener tools) are re-export shims until Phase 2.
- `backend/app/schemas/` — Pydantic contracts (source of truth; TS types mirror them)
- `backend/app/extraction/` — Gemini client, PDF/image ingestion, prompts
- `backend/app/population/` — Playwright fill, field map, verification
- `backend/app/screener/` — criteria registry (USCIS knowledge as data), LangGraph graph + nodes, citation audit, evidence extraction, grounded web tool, APIRouter
- `backend/app/storage/` — Supabase + local fallback behind 3-method interface
- `backend/validation/` — extraction personas + screener personas and eval runners
- `frontend/` — Next.js App Router upload UI + review table + `/screener` wizard
- `docs/` — architecture, tech research, field map, agent usage log

## Commands
- `make dev` — backend :8000 + frontend :3000
- `cd backend && pytest` — golden tests skip (not fail) when fixtures/key absent
- Population tests run against `backend/tests/data/form_snapshot.html` offline; live-URL runs are explicit
- `cd backend && python -m validation.run_screener_validation` — live screener eval (8 personas, enrichment off, exit 1 on any overclaim) → docs/screener-validation-report.md
