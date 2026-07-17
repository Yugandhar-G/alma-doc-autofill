# Architecture

Local-first document automation pipeline: upload passport + G-28 → vision-LLM extraction → human review table → deterministic Playwright population of the target form. Never submits, never signs.

```
┌──────────────────────────────────────────────────────────────┐
│ frontend/  Next.js (localhost:3000)                          │
│   upload (2 slots, PDF/JPEG/PNG) → review table (editable)   │
│   → Populate button → population report                      │
└───────────────┬──────────────────────────────────────────────┘
                │ HTTP (JSON envelope {success, data, error})
┌───────────────▼──────────────────────────────────────────────┐
│ backend/  FastAPI (localhost:8000)                           │
│                                                              │
│  EXTRACTION PLANE  app/extraction/                           │
│   magic-byte sniff → guardrails (size/pages/resolution/blur) │
│   → image direct | PDF→PNG (PyMuPDF, config DPI)             │
│   → Gemini structured JSON (temp 0, null-never-guess)        │
│   → Pydantic validation → post-validators (ISO date, state,  │
│     sex enums; failures null + warn) → ExtractionEnvelope    │
│                                                              │
│  STORAGE  app/storage/   (3-method interface)                │
│   Supabase Storage+Postgres when configured; local disk      │
│   fallback — reviewer needs only GEMINI_API_KEY              │
│                                                              │
│  HUMAN GATE  review table in frontend                        │
│   populate is unreachable except through user-reviewed data; │
│   edits re-validate through the same schemas                 │
│                                                              │
│  POPULATION PLANE  app/population/                           │
│   allow-list FIELD_MAP → Playwright fill/select_option/check │
│   → post-fill read-back diff → PopulationReport              │
│   submit/sign selectors structurally absent                  │
└──────────────────────────────────────────────────────────────┘
```

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Extraction | Gemini Flash-class default, Pro-class escalation, behind `extract_document()` interface | Best cost/quality for vision extraction per tech-research.md; interface keeps vendor swappable |
| Null policy | absent/N-A/illegible → null, never guess | A null is recoverable by review; a plausible wrong value silently propagates |
| Normalization | at extraction time (ISO dates, full state names, M/F/X) | Target form uses `input[type=date]` (needs ISO) and label-matched selects |
| Population | deterministic Playwright, id-keyed allow-list | Known form → AI browser agents add cost and 12–17 pts less reliability; recon found traps requiring exact selectors |
| Storage | Supabase with automatic local fallback | User decision; fallback preserves the assignment's "minimal setup" requirement |
| Deploy | local only, Vercel later | Playwright can't run on Vercel serverless; assignment requires local anyway |
| Config | everything in `app/config.py` / env | no hardcoded model ids, URLs, caps, or thresholds at call sites |
| Observability | Langfuse (`app/observability.py`), no-op unless `LANGFUSE_*` keys set | Traces per request (grouped by frontend `X-Session-Id`), Gemini generation spans with token usage, UI events via `/api/telemetry`. PII-redacted by design: hashes, timings, counts, and field statistics only — never images, prompts' page content, or extracted values |

## Target-form traps (verified by DOM recon before any code)

See `docs/field-map.md`. Highlights: duplicate `passport-given-names` id on two different inputs (middle name addressed positionally), discipline "radio" that is really two independent checkboxes, state dropdown whose option values are 2-letter codes while labels are full names, `<span for=>` pseudo-labels that break label-based selection.

## Production path (short form)

Three-plane evolution: governed ZDR/VPC extraction endpoint + deterministic MRZ/checksum validators; multi-signal confidence routing documents to auto-accept / field-flag review / full review (review seconds per document is the KPI — attorneys review anyway); population stays deterministic with AI selector-healing only as drift fallback. Golden-set evals gate every model/prompt/schema change in CI. Full analysis: `docs/tech-research.md`.

## Screener plane (O-1A / EB-1A eligibility, added 2026-07-15)

Agentic decision support built on the same thesis: a **deterministic LangGraph
skeleton whose nodes make schema-bound Gemini calls** — the LLM reasons inside
nodes, code owns the path, the human owns the evidence.

```
POST intake ─┐        (REST, pre-graph: guardrails + evidence extraction,
POST documents ┘        verbatim key-fact excerpts, per-slot error isolation)

START → compile_matrix          claims → criteria mapping, pre-audited sources
      → review_gate             interrupt(): HUMAN edits/confirms the matrix
      → [verify_profile?]       pure route: flag ∧ key ∧ claims>0
      │    TOOL-LOOP AGENT: model picks searches/fetches; code owns the
      │    allow-listed tools (search_web grounding, fetch_page SSRF-guarded),
      │    the call budget, the only-fetch-searched-URLs rule, and the
      │    transcript audit (evidence URLs must have actually been seen;
      │    absence of evidence = unverified, never contradicted)
      → plan_assessments ─ Send fan-out ─ assess_one × ≤10 criteria (parallel;
      │    contradicted claims cannot support met/likely)
      → merits_gate → [final_merits?]   pure route: EB1A ∧ ≥3 met/likely (Kazarian step 2)
      → verdict (per visa; model narrates, CODE counts criteria + arithmetic caps)
      → profile_summary         strengths / eligibility drivers / bounce-back risks
      → assemble_report         deterministic citation audit + constant disclaimer
      → END
```

- **Anti-fabrication contract**: every claim cites an intake `answer_id`, a doc
  hash + verbatim excerpt (substring-audited against the extraction), or a
  grounded URL. Invalid refs stripped; uncited positive verdicts downgraded to
  not_met + warning. Eval harness treats any overclaim as a hard failure
  (`validation/run_screener_validation.py`, 8 personas incl. a fabrication-bait
  empty record).
- **HITL**: `review_gate` is a real LangGraph interrupt spanning HTTP requests;
  checkpoints in SQLite (`uploads/screener/checkpoints.db`) so review survives
  reloads. Edited matrices re-validate through the same schema + source audit.
- **Live agent feed**: run/review are SSE streams with two event families —
  lifecycle (`node_finished`, `awaiting_review`, `done`) and genuine activity
  (`evidence_scan` = actual excerpts being read, `model_thinking` = Gemini
  thought summaries streamed token-by-token, `finding`, `web_lookup`). Nothing
  templated. Session-owner stream only; Langfuse traces stay masked.
- **USCIS knowledge as data**: `screener/criteria.py` — 10 CriterionSpecs with
  8 CFR refs, adjudicator-accepted evidence, and RFE trigger patterns; prompts
  interpolate from the registry, so the legal framing has one reviewable home.
- **Registry**: O-1A = 8 criteria (8 CFR 214.2(o)(3)(iii)(B)), EB-1A = those
  plus exhibitions + commercial success (8 CFR 204.5(h)(3)), threshold 3 each,
  one-time-major-award short-circuit handled in the verdict narrative.
