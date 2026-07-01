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
