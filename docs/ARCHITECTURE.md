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

## Target-form traps (verified by DOM recon before any code)

See `docs/field-map.md`. Highlights: duplicate `passport-given-names` id on two different inputs (middle name addressed positionally), discipline "radio" that is really two independent checkboxes, state dropdown whose option values are 2-letter codes while labels are full names, `<span for=>` pseudo-labels that break label-based selection.

## Production path (short form)

Three-plane evolution: governed ZDR/VPC extraction endpoint + deterministic MRZ/checksum validators; multi-signal confidence routing documents to auto-accept / field-flag review / full review (review seconds per document is the KPI — attorneys review anyway); population stays deterministic with AI selector-healing only as drift fallback. Golden-set evals gate every model/prompt/schema change in CI. Full analysis: `docs/tech-research.md`.
