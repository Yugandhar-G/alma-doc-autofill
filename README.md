# alma-doc-autofill

Upload a passport and a Form G-28 (PDF or JPEG/PNG) → structured data is extracted with a vision LLM → review and edit the results in a table → Playwright fills the target form at https://mendrika-alma.github.io/form-submission/ and verifies every field it wrote. The app never submits or signs anything.

## Setup

Requirements: Python 3.11+, Node 20+, a Gemini API key.

```bash
git clone https://github.com/Yugandhar-G/alma-doc-autofill.git
cd alma-doc-autofill
cp .env.example backend/.env   # add your GEMINI_API_KEY
make install                   # python venv + deps + chromium, npm install
make dev                       # backend :8000 + frontend :3000
```

Open http://localhost:3000, upload the two documents, review the extracted fields, hit Populate — a Chromium window opens and fills the form in front of you, then reports exactly what was filled, skipped, or mismatched.

Supabase storage is optional: set `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` to use it; otherwise uploads persist to local disk (`backend/uploads/`, gitignored).

## Tests

```bash
make test
```

The golden extraction test runs field-level assertions against the example G-28 (drop fixtures into `backend/tests/fixtures/` — see the README there). It skips cleanly when fixtures are absent. Population logic is tested offline against a saved snapshot of the target form.

## Design

- `docs/ARCHITECTURE.md` — three-plane design, decision log
- `docs/field-map.md` — target-form DOM recon (including the planted duplicate-id trap) and the full source→form mapping
- `docs/tech-research.md` — production-architecture research behind the design choices
- `docs/agent-usage-log.md` — coding-agent prompts, mistakes, and corrections (assignment deliverable)

## Safety properties

- Extraction contract: absent/"N/A"/illegible → null, never guessed; normalization (ISO dates, full state names, M/F/X) happens at extraction time.
- Population iterates an allow-list field map; submit/sign/Part 4/Part 5 selectors do not exist anywhere in population code.
- Post-fill verification reads every touched field back and diffs — silent partial failures become loud reports.
- PII: uploads and fixtures are gitignored, documents are referenced by content hash in logs, secrets live in `.env` only.
