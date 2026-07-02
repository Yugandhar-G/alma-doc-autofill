# Agent Usage Log (append-only)

Raw evidence for the coding-agent-usage writeup: prompts given to agents, what they produced, what was wrong, and how it was corrected. Newest entries at the bottom. Times local (PT), 2026-07-01.

---

## Session 1 — Planning & recon

**~16:10 — Scoping.** Handed the agent the assignment + a pre-written master brief (architecture, build sequence, extraction prompt contract, golden test, field mapping spec). Design decisions were made before the agent touched anything: null-never-guess contract, review table as core (not polish), deterministic Playwright over AI browser agents, normalize-at-extraction.

**~16:15 — Agent-initiated DOM recon (good catch).** Before accepting the brief, the agent fetched the live target form and diffed its actual DOM against the brief's assumptions. Findings that changed the plan:
1. Part 3 First Name(s) and Middle Name(s) both carry `id/name="passport-given-names"` — a planted duplicate-id trap; label/id selection would silently overwrite first name with middle name. Fix: positional `nth(1)`.
2. Discipline 1.c is two independent checkboxes, not radios (brief said radio).
3. Only two dropdowns (state, sex) — brief claimed three (country is a text input).
4. State option values are 2-letter codes while labels are full names → must `select_option(label=...)`; brief said "by exact option value", which would have failed.
5. All dates are `input[type=date]` → ISO-only `fill()`, making normalize-at-extraction load-bearing.
Also: Part 2 checkboxes 1.a/2.a use `<span for=>` (invisible to `get_by_label`) → strategy changed from label-first to id-keyed allow-list. And no submit button exists anywhere on the form.

**~16:25 — Architecture rulings (user decisions, agent asked before changing anything).**
- LLM: Gemini (Flash default, Pro escalation) behind a swappable `extract_document()` interface.
- Storage: Supabase, with automatic local-disk fallback so a reviewer needs only GEMINI_API_KEY.
- Deploy: local only for now (agent flagged that Playwright cannot run on Vercel serverless; Vercel deferred).
- Frontend: Next.js, built in parallel with backend by subagents.

**~16:30 — User corrections during planning (pushback log).**
1. Agent's plan under-specified image ingestion → corrected: images AND PDFs are first-class inputs for both document types (magic-byte sniffing, not extensions).
2. "What about guardrails?" → plan revised with an explicit enforced-in-code guardrail section (upload boundary, wrong-document detection, validator-null-and-flag, human gate, PII rules).
3. "No hardcoding anywhere" → every tunable moved to `app/config.py`/env; field mapping is data (`FIELD_MAP` tuple); stubs return empty schemas, not canned people.

**~16:40 — Phase 0 scaffold (main agent, sequential).** PII-safe .gitignore as the FIRST commit, then repo `Yugandhar-G/alma-doc-autofill` created. Contracts written before any parallel work: Pydantic schemas, extraction prompt contract (`prompts.py`), allow-list `FIELD_MAP` encoding all five recon findings, FastAPI shell, 3-method storage interface. Rationale: parallel agents can't drift if the interfaces they must satisfy are already committed.

---

## Session 1 — Parallel build (entries added as agent loops run)

**~16:50 — Environment catch before agent launch.** First dependency install silently used Python 3.10 (system default) against a `requires-python = ">=3.11"` project — pip churned for 8+ minutes. Caught it by inspecting the running process, killed it, recreated the venv with uv + Python 3.13; install finished in seconds and Chromium launch was verified before any agent depended on it. Lesson applied: verify the interpreter before letting three agents build on the environment.

**~16:55 — Three Fable subagents launched in parallel, each with hard ownership boundaries** (may only edit their own directories; contracts frozen; no git access — orchestrator reviews diffs and commits). Each prompt specified: goal, frozen interfaces, implementation requirements keyed to the recon findings, verification the agent must run itself before reporting, and an explicit "report deviations with reasoning" clause.
- **Agent A (extraction):** Gemini structured-output engine, dual PDF/image ingestion with magic-byte sniffing, quality gates, post-validators that null-and-warn, escalation tier, storage (Supabase + local fallback), golden test against the real Example_G-28.pdf with the N/A→null trap assertions, offline unit tests. Allowed to correct the placeholder Gemini model ids in config — only with evidence from Google's official docs.
- **Agent B (population):** async Playwright fill consuming the frozen FIELD_MAP allow-list; the nth(1) duplicate-id trap; select-by-label state; pseudo-radio checkbox pair; post-fill read-back verification report; offline tests against the committed form snapshot via file://; a safety test asserting no signature selectors and no .click() exist in population code. Told explicitly: if FIELD_MAP looks defective, report it, don't edit it.
- **Agent C (frontend):** Next.js App Router upload → editable review table → populate report UI against the committed API envelope contract; no mock data, no hardcoded URLs; must pass build + lint before reporting.

---

## Session 2 — Frontend wizard (parallel to Session 1's backend work)

**~16:55 — User prompt (verbatim intent).** "While my other session is working on backend, let's focus on frontend. Build a frontend app where it gets prompted for user passport front first (validate) and back (validate), and ask user for feedback if the extracted information is correct; then user G-28 form being dropped, ask user for validation, then fill the G-28."

**~16:55 — Design decision surfaced before building.** The backend `/api/extract` contract takes one passport file per call, so passport front and back are extracted in two calls and merged client-side (front authoritative, back only fills nulls — `src/lib/passportMerge.ts`). Back sides rarely carry data, so a non-passport detection on the back is a non-blocking amber notice, while a non-passport front or non-G-28 upload is a hard rejection with re-upload.

**~17:00 — Built by the main agent (no subagents).** Six-step wizard in `frontend/`: passport front → passport back → editable passport review ("Is this information correct?") → G-28 upload → editable G-28 review (Parts 1–3 sections) → populate + read-back report. TS types mirror the Pydantic schemas 1:1; client-side guardrail mirror (magic-byte sniffing, 10 MB cap) fails fast before upload; nulls render as explicit "missing" badges and empty inputs round-trip back to null, never to guessed values. A fresh upload marks review data stale so confirmed edits survive navigation but re-uploads reset cleanly.

**~17:05 — Cross-session collision caught and reconciled.** Mid-build, Session 1's frontend agent refactored `src/lib/api.ts` (single `extractDocument` → per-slot `extractDocuments` returning `SlotResult`), added `src/lib/config.ts`, and extended `types.ts`. Instead of reverting or duplicating, the wizard was adapted to the new surface: slot-level guardrail rejections (`{kind:"rejected"}`) now render as upload errors, and the upload step reads `FILE_ACCEPT`/`MAX_FILE_MB` from the shared config module rather than hardcoding.

**~17:10 — Verification actually run.** `npm run build` green (one TS error fixed: G-28 section record cast). Full six-step flow driven headlessly with Playwright against a mocked backend (route-intercepted `/api/extract` and `/api/populate`): front extraction summary, back-side "detected: other" notice path, editable passport review with missing badge + field warning, G-28 three-section review, and the population report table incl. filled/skipped_null/mismatch chips — screenshots captured per step. Dev server stopped afterwards to avoid clashing with Session 1's `make dev`.

---

## Session 1 (continued) — Agent B review

**~17:05 — Agent B (population) reported complete.** Its own verification: 12/12 offline tests passing against the form snapshot (duplicate-id trap covered: after the run, given-names input nth=0 still holds the first name and nth=1 holds the middle name; "California" label → selected value "CA"; discipline False → #not-subject checked AND #am-subject verified unchecked; apt/ste/flr null → all boxes audited unchecked), plus a live headless smoke against the real URL: one field filled and verified, 39 skipped_null, 0 mismatches, 0 errors.

**~17:08 — Orchestrator review (trust but verify).** Reran the full population suite independently (12 passed) and the safety greps myself: no signature-selector strings, no `.click(` anywhere in population code. Read `fill.py` and `verify.py` line-by-line. Accepted with two notes:
1. Agent's design call, accepted with rationale: intentionally-unchecked checkboxes (e.g. `#am-subject` when discipline is False) report status `filled` (verified unchecked) because the frozen status enum has no "verified no-op" value — documented in the module docstring rather than silently mislabeled. Correct instinct: it flagged the schema limitation instead of editing the frozen contract.
2. Agent surfaced that the headed browser closes immediately after verification and proposed a settings addition rather than hardcoding a sleep — deferred to integration (orchestrator owns config.py).
No corrections needed; the boundary discipline held (frozen files untouched, no commits).
