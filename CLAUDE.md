# Project Rules — alma-doc-autofill

Document automation take-home: upload passport + G-28 → Gemini vision extraction → editable review table → Playwright populates https://mendrika-alma.github.io/form-submission/. Runs fully local. Never submits or signs anything.

## Governance
- Any architectural change (LLM vendor, storage, deployment, framework, new dependency category) → ask the user first. Locked decisions: Gemini extraction, Supabase storage with local-disk fallback, local-only deploy (Vercel later), Next.js frontend, FastAPI backend.
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

## Layout
- `backend/app/schemas/` — Pydantic contracts (source of truth; TS types mirror them)
- `backend/app/extraction/` — Gemini client, PDF/image ingestion, prompts
- `backend/app/population/` — Playwright fill, field map, verification
- `backend/app/storage/` — Supabase + local fallback behind 3-method interface
- `frontend/` — Next.js App Router upload UI + review table
- `docs/` — architecture, tech research, field map, agent usage log

## Commands
- `make dev` — backend :8000 + frontend :3000
- `cd backend && pytest` — golden test skips (not fails) when fixtures absent
- Population tests run against `backend/tests/data/form_snapshot.html` offline; live-URL runs are explicit
