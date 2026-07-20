# package_author — agent-authored packages devtool (Phase E1)

A dev-time CLI where an agent fan-out **DRAFTS** a new vertical package's
artifacts and a **code-owned acceptance pipeline** gates them.

**Agent-authored ≠ agent-installed.** The agents only ever write into a
per-run sandbox. Installing a candidate — adding it to `app/registry.py` — is a
**human** action taken after reading the acceptance verdict. This tool never
touches `app/registry.py`.

## Run

```bash
cd backend
.venv/bin/python -m devtools.package_author \
    --brief <path-to-brief.md> \
    --candidate-id <slug>
```

Flags:
- `--budget N` — tool-call budget per authoring agent (default 10).
- `--skip-authoring` — skip the live fan-out and only gate an existing
  candidate (useful while iterating on the pipeline).
- `--no-pytest` — skip the full-suite pytest gate for faster iteration.

The fan-out step calls **live Gemini** (`make_agent_model`), so it needs
`GEMINI_API_KEY` in `backend/.env`. It does not run in CI.

## What happens

1. **Fan-out.** Four `run_tool_loop` agents (one per artifact family:
   `knowledge`, `schemas`, `eval`, `graph`), each granted **only** two
   code-owned tools:
   - `read_exemplar(path)` — reads under `app/packages/` or the file
     `app/kernel/package.py`; anything else → `READ_REFUSED`.
   - `write_candidate(relpath, content)` — writes **only** under
     `app/packages/_candidates/<candidate_id>/`; absolute paths and `..`
     escapes → `WRITE_REFUSED`.

   `GrantEnforcementMiddleware` refuses every other tool name
   (`write_file`, `execute`, …) with `UNKNOWN_TOOL` at the execution layer.
   Each agent studies the **preflight exemplar** via `read_exemplar` before
   writing. The live registry is structurally unreachable from the sandbox.

2. **Acceptance pipeline** (pure code, `acceptance.py`):
   - **compile** — every candidate `.py` compiles (`py_compile`).
   - **import** — the package imports in an isolated subprocess (`_inspect.py`,
     a fresh interpreter, so import-time side effects cannot corrupt the CLI).
   - **package** — exports `PACKAGE: WorkflowPackage` with a validating manifest.
   - **lint** — its schemas pass the shared Gemini response-schema lint rules
     (`app/kernel/schema_lint.py`, the same rules `tests/test_schema_lint.py`
     enforces on shipped models).
   - **eval** — its eval kit runs through the kernel `Harness` offline, exits
     `0`, with zero worst-class results.
   - **pytest** — the full suite is still green.

   A PASS/FAIL verdict per gate is printed and written to
   `app/packages/_candidates/<candidate_id>/ACCEPTANCE.md`.

## Candidate contract

The candidate mirrors `app/packages/preflight/` and must export, from
`package.py`, a `PACKAGE = WorkflowPackage(...)` whose:
- `manifest.package_id`, `version`, `title` are non-empty,
- `state_model` is a Pydantic `BaseModel`,
- `build_graph` is callable,
- `eval_kit` is a **zero-arg callable returning a kernel `Harness`**
  (i.e. `eval_kit=build_harness`).

Schemas to lint = the `state_model` plus every `BaseModel` defined in the
candidate's `schemas.py`.

## Dogfood: I-864-registry-regeneration (do NOT run here)

The reference dogfood regenerates the I-864 (Affidavit of Support) knowledge
registry as an authored candidate, to prove the tool can reproduce checked-in
reference data an agent never hand-wrote.

```bash
# Needs GEMINI_API_KEY. Not part of CI. Run from backend/.
.venv/bin/python -m devtools.package_author \
    --brief docs/briefs/i864-registry.md \
    --candidate-id i864-refresh
```

**What to diff after a run:**

1. **Knowledge registry vs. the shipped reference.** Diff the candidate's
   authored knowledge tables against the existing checked-in reference the
   brief points at (e.g. `app/forms/data/forms_registry.json` and
   `app/packages/preflight/knowledge/poverty_guidelines.py`):

   ```bash
   diff <(python -m json.tool app/packages/_candidates/i864-refresh/knowledge/i864.json) \
        <(python -m json.tool app/forms/data/forms_registry.json)
   ```

   The interesting signal is where the agent's regenerated poverty-guideline
   figures / form-edition strings **differ** from the authoritative data — any
   divergence is a fabrication defect, exactly what the extraction contract
   forbids. A faithful regeneration diffs to nothing material.

2. **`ACCEPTANCE.md`.** Read the per-gate verdict. A candidate that fails
   `lint` or `eval` never reaches a human's registry decision.

3. **Never diff into `app/registry.py`.** Installing is a separate, manual
   step. The tool's job ends at the verdict.

`app/packages/_candidates/` contents are gitignored (except `.gitkeep`): a
candidate is runtime output, not a committed artifact.
