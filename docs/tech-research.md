# Technology Research: Production-Grade Document → Extraction → Form-Population Pipeline
Date: 2026-07-01 | Confidence: High (extraction stack), Medium (cost trajectory, population long-term) | Type: Architecture decision (Deep calibration)

## Research Question
What is the production-grade, end-to-end architecture for an immigration document pipeline (passport + G-28 upload → structured extraction → web form population), built API-first for fastest time to production, and which technologies at each layer are production-ready as of mid-2026?

## Hypothesis (initial → outcome)
**Initial:** FastAPI + async job queue; frontier vision LLM with schema-constrained structured outputs + deterministic MRZ cross-check + confidence-gated human review; Playwright workers for population; golden-set evals in CI; tracing; PII encryption/retention as first-class.

**Outcome: CONFIRMED with three material refinements.**
1. Token logprobs are NOT a viable confidence signal for extraction — they fail structurally (0.705 ROC AUC on DocILE where frontier LLMs miss 26% of fields; a model confidently transcribing noise produces high logprobs for a wrong answer). Confidence must be multi-signal: deterministic validators + MRZ agreement + dual-model challenge.
2. The production consensus for browser automation is hybrid: deterministic DOM-driven Playwright as primary, AI only as fallback. DOM-driven stacks are 12–17 percentage points more reliable than vision-driven agents on common tasks, at a fraction of the cost.
3. Straight-through automation has a practical ceiling. Alan (French insurtech) reached ~70% automation on document processing with a mature eval-driven pipeline. Design for a human-review lane from day one, not as an afterthought.

## Executive Summary
Build a three-plane system: an **extraction plane** (frontier VLM via a zero-data-retention or VPC endpoint, schema-constrained JSON, deterministic MRZ/checksum validators), a **decision plane** (multi-signal confidence scoring that routes each document to auto-accept, field-level review, or full review), and an **action plane** (deterministic Playwright workers that populate the target form, never submit, and emit full traces). Every layer is instrumented into a golden-set eval harness so no model, prompt, or schema change ships without a field-level regression diff. The fastest credible path to production is roughly two weeks for a single-document-type pipeline; the architecture below is designed so adding document types is a schema + eval-set change, not a code change.

---

## Target Architecture

```
                        ┌─────────────────────────────────────────────┐
                        │  Web app (upload, review UI, audit views)    │
                        └───────────────┬─────────────────────────────┘
                                        │ HTTPS
     ┌──────────────────────────────────▼──────────────────────────────────┐
     │ FastAPI API layer                                                    │
     │  - multipart upload → S3 (SSE-KMS), row in Postgres, job enqueued    │
     │  - signed URLs, RBAC, audit log on every read/write of PII           │
     └──────────────────────────────────┬──────────────────────────────────┘
                                        │ Redis / SQS
     ┌──────────────────────────────────▼──────────────────────────────────┐
     │ Worker pool (Celery or Temporal)                                     │
     │                                                                      │
     │  1. INGEST     pdf→png render (PyMuPDF), format sniffing, image      │
     │                quality gate (blur/resolution check → early reject)   │
     │  2. CLASSIFY   doc type → schema registry lookup                     │
     │  3. EXTRACT    VLM (ZDR/VPC endpoint) + Pydantic schema → JSON       │
     │                rule: absent/"N/A"/illegible → null, never guess      │
     │  4. VALIDATE   deterministic layer:                                  │
     │                - MRZ parse (FastMRZ) + ICAO 9303 checksums           │
     │                - field normalizers (dates, ISO country, state, sex)  │
     │                - cross-document coherence (name join, visa logic)    │
     │  5. SCORE      multi-signal confidence per field + per document      │
     │  6. ROUTE      auto-accept │ field-flag review │ full review         │
     └──────────────┬────────────────────────────────┬─────────────────────┘
                    │                                │
     ┌──────────────▼──────────────┐   ┌─────────────▼─────────────────────┐
     │ Human review queue           │   │ POPULATE (on approval)            │
     │  side-by-side doc + fields   │   │  Playwright worker, headed-trace  │
     │  corrections → eval dataset  │   │  getByLabel/getByRole hierarchy   │
     └──────────────────────────────┘   │  fill/select_option/check only    │
                                        │  hard-block on submit selectors   │
                                        └───────────────────────────────────┘
     Cross-cutting: Langfuse/LangSmith tracing · per-field metrics · cost/doc
     · golden-set eval harness in CI · retention TTL & deletion pipeline
```

---

## Layer-by-Layer Analysis

### L1 — Ingestion and preprocessing
PDFs are rendered to page images (PyMuPDF; 200–300 DPI) before extraction, since scanned PDFs are images and the VLM path is image-native. Add an image-quality gate (Laplacian blur score + minimum resolution) that rejects unusable uploads *before* burning an inference call — this is cheap and eliminates a whole class of garbage-in errors that no downstream layer can fix. A frontier LLM will confidently transcribe OCR noise; the multi-signal confidence research shows unreadable source material is a top cause of high-confidence wrong extractions, so catching it at ingest is the highest-leverage defense. Store the original bytes immutably (they are the audit source of truth); derived artifacts (page PNGs, extraction JSON) are reproducible and can carry shorter retention.

### L2 — Extraction engine (the core decision)
**Choice: frontier VLM through a governed endpoint, with schema-constrained structured outputs.** The 2026 evidence is clear that no single model wins everything: specialized OCR models (GLM-OCR 94.62, PaddleOCR-VL 94.50 on OmniDocBench) beat frontier models on raw character recognition, but the task here is *semantic field extraction into a schema*, where frontier models lead — GPT-5.2 tops JSON-schema extraction (0.888 json-diff accuracy) despite ranking 14th on flat OCR; Claude Opus 4.6 leads complex structured extraction; Gemini 3.1 Pro/Flash lead cost-per-page for volume. Field accuracy and document accuracy are different metrics — a document is only automatable if *every* field is right, and benchmark data shows no one model dominates across datasets, which is why the eval harness (L8), not vendor benchmarks, makes the final call on your documents.

Deployment mode is gated on the data-governance answer (CTO Q2):
- **ZDR API agreement** (Anthropic / OpenAI / Google enterprise terms, no training, zero retention) — fastest, full frontier accuracy.
- **VPC-contained inference** — Claude via AWS Bedrock or Gemini via Vertex AI. Same models, traffic never leaves the cloud tenancy; the default answer for a SOC 2-conscious company already on AWS/GCP.
- **Prebuilt ID APIs** are not the answer: Textract AnalyzeID supports only US passports/driver's licenses (dealbreaker for international passports); Mindee's passport model is credible but adds a vendor for one document type that the VLM already handles.

Engineering rules that matter more than model choice: all schema fields optional with `null` default; explicit prompt contract "absent, N/A, or illegible → null — never infer"; temperature 0; page images at native resolution (no aggressive downscaling); one document type per call (don't batch passport + G-28 into one prompt — isolation improves both accuracy and debuggability). Use a **model-router**: cheap tier (Flash-class) as default, escalate to the accuracy tier (Opus/GPT-5.2-class) automatically when the confidence layer flags a document — this is how you get frontier accuracy at commodity average cost.

**Self-hosted (rejected as primary, kept as documented exit ramp).** Self-hosted structured-extraction VLMs are genuinely production-viable in 2026 — JSL Vision Structured-8B beats Claude Sonnet 4.5 on schema-JSON on a single A10G, NuExtract3 (4B, Apache 2.0, ~10 GB VRAM) outperforms sub-30B models on OCR+extraction, and self-hosted OCR compute runs ~167× cheaper per page than commercial vision APIs. But it loses on the two things that matter now: time-to-production (vLLM ops, GPU capacity, model-quality ownership ≈ weeks of engineering before the first correct extraction) and peak accuracy on ambiguous documents. The architecture keeps the exit ramp open by hiding the model behind an internal `extract(image, schema) → json` interface: if volume, cost, or a data-sovereignty mandate later triggers it, swap the backend without touching the pipeline. Trigger points: >~50k pages/month sustained, or a customer/regulatory requirement that rules out external inference even in-VPC.

### L3 — Deterministic validation (the senior differentiator)
This layer costs days to build and removes the biggest failure class: plausible-looking wrong values.
- **MRZ cross-check.** Every passport carries an ICAO 9303 machine-readable zone with check digits over passport number, DOB, and expiry. FastMRZ (contour detection + custom ONNX models, TD1/TD2/TD3 support, built-in checksum validation, JSON output) is the current pick; PassportEye is the fallback (older, Tesseract-dependent, but exposes a useful 0–100 `valid_score`). The MRZ is a *deterministic second opinion* on exactly the fields where a transposed digit is catastrophic. VLM–MRZ agreement on a checksum-valid MRZ is the strongest single auto-accept signal in the system.
- **Field normalizers.** Dates → ISO 8601 with explicit day/month disambiguation rules per document origin; countries → ISO 3166 via pycountry; US states, sex markers → controlled vocab matching the target form's option values. Normalize at extraction time, not at fill time.
- **Cross-document coherence.** Join the case on beneficiary name (fuzzy match, transliteration-aware); flag mismatches. Domain rules where cheap (e.g., visa-class ↔ nationality consistency) surface as review-queue warnings, not hard failures.

### L4 — Confidence scoring and routing
The naive approaches measurably fail: on a 55-field extraction benchmark where frontier LLMs err on 26% of fields, mean logprob scores 0.705 AUC and collapses to an all-positive classifier at practical thresholds; verbalized self-confidence scores 0.692; five-way self-consistency reaches only 0.744 at 5× the API cost. Several frontier providers (Anthropic included) don't expose logprobs anyway. Production-grade confidence is **multi-signal**, combining signals the generating model cannot see:
1. Deterministic validator results (checksum pass/fail, format validity, normalizer success).
2. MRZ agreement per field (passports).
3. **Dual-model challenge**: a second, different model extracts independently (or critiques field-by-field); disagreement → field set to null and flagged. This "LLM-challenge → null" pattern is established in production IDP (a null is recoverable by a human; a wrong value silently propagates).
4. Image-quality score from L1.
5. Optional: a dedicated trust-scoring service (Cleanlab TLM / CONSTRUCT-class) — detects structured-output errors with ~25% better precision/recall than LLM-as-judge and works on black-box APIs; adopt if building the in-house signal combiner stalls.
Routing: all critical-field signals green → auto-accept; isolated field disagreements → field-flag review (reviewer sees only flagged fields with document crop alongside); systemic failure (MRZ unreadable, low image quality, coherence mismatch) → full review. Thresholds are set empirically from the eval set against the wrong-field-cost answer from the CTO (Q1).

### L5 — Human review loop
A side-by-side UI: document image (with the source region highlighted where available) next to editable extracted fields, flagged fields first. Two design rules with compounding value: **every human correction is captured as a labeled example** and flows into the golden eval set (the feedback loop is the moat — Alan's automation rate climbed because corrections became training/eval data), and reviewers approve *before* population runs, making the human the gate on the side-effectful action — which matches an attorney-led compliance posture where a lawyer signs the filing anyway.

### L6 — Form population
**Deterministic Playwright, Python, running headed-with-tracing in workers.** For a known target form, an AI browser agent is the wrong tool — you'd pay per-step LLM cost and 12–17 points of reliability to solve a problem (unknown page structure) you don't have. Production rules, in order of impact:
- **Selector hierarchy**: `getByLabel`/`getByRole` first (survives DOM refactors; matches how the form is human-labeled), `getByTestId` where obtainable, CSS only as last resort, never XPath. Selector fragility accounts for roughly half of "worked last week" automation failures.
- Interact only via `fill()` / `select_option()` / `check()` — these fire real focus/input/change/blur events so client-side validation runs; setting DOM values directly silently bypasses it.
- **Post-fill verification pass**: after populating, read every field back and diff against intended values; emit a population report. This converts silent partial failures into loud, reviewable ones.
- **Hard safety interlock**: the worker's allowed-action list excludes submit/sign selectors entirely (deny-by-default, not "remember not to click"); Parts 4/5 signature fields are structurally unreachable.
- Trace + video artifacts on every run, retained with the case audit trail.
- **Escalation path when target forms drift** (relevant only if targets are third-party portals — CTO Q3): Playwright MCP's Healer-style auto-repair or Stagehand's `act()` as a *fallback layer that proposes* a selector fix for human approval, cached thereafter (Stagehand's cache amortizes LLM cost to ~zero on repeated workflows). Skyvern-class vision agents only if you must generalize across many unseen government portals — that's a different product with per-step vision costs.
- If the target form is Alma-owned: say so in the design doc and propose a structured submission API; browser automation of your own form is technical debt with an expiration date.

### L7 — Orchestration
Celery + Redis (or SQS) is sufficient and fastest to stand up: the pipeline is a linear DAG per document, steps are idempotent, retries with exponential backoff + a dead-letter queue cover the failure modes. Temporal earns its complexity only when workflows become long-lived and stateful across days (multi-party document collection, human steps interleaved with machine steps at case level) — a plausible 12-month destination, not a week-one requirement. Whichever engine: every step idempotent (keyed on document content hash), every state transition persisted in Postgres, no in-memory-only state.

### L8 — Evals and CI (the layer that keeps it production-grade)
Adopt the Alan pattern wholesale, it is the best-documented production reference found: a **reference dataset** of real documents with human-verified extractions; a **backtest** that re-runs the full pipeline (render → classify → extract → validate → score) against it; a **field-level diff report** (per-field exact-match, per-document all-fields-correct rate, confusion on nulls: fabricated-value rate vs missed-value rate) gating every model, prompt, or schema change in CI. Track *document accuracy* (all fields correct) as the automation KPI, not field accuracy — 98% field accuracy on a 20-field doc is ~67% document accuracy. Seed the set from historical labeled cases if they exist (CTO question), grow it from review-queue corrections. Separate a held-out set that engineers never look at. Add synthetic hard cases: low-DPI scans, rotated pages, N/A-riddled forms, non-Latin transliterations, passports from the top-10 origin countries in the case mix.

### L9 — Observability
Trace every pipeline run end-to-end (Langfuse self-hostable if subprocessor-count matters, LangSmith otherwise): inputs (doc hash, not raw PII in trace metadata), model+version, prompt version, per-field outputs and confidence, validator results, route taken, human corrections, population report. Dashboards: automation rate, per-field error rates over time, review-queue latency, cost per document, model-router escalation rate. Alert on drift: a new passport format or a silent model-version change shows up as a validator-failure spike before customers notice.

### L10 — Security and compliance (immigration PII is the product's license to operate)
Alma is SOC 2 Type I and in observation for Type II — the design must not jeopardize that. Requirements: encryption at rest (KMS, per-tenant keys if multi-tenant) and TLS in transit; RBAC with least privilege; immutable audit log of every access to documents and extracted PII; retention TTLs with a real deletion pipeline (source docs, derived images, traces, model-provider logs — ZDR terms close the last one); vendor DPAs for every subprocessor (model provider, tracing vendor, browser infra if any); no PII in application logs or error trackers (scrub middleware); secrets in a manager, never env-committed. Passport data is not special-category under most regimes but immigration context makes it high-sensitivity in practice — treat it at a KYC standard.

---

## Ecosystem Map (companies, stacks, patterns)

| Company | What they build | Relevant stack signal | Pattern |
|---|---|---|---|
| Alan (insurtech, FR) | LLM doc pipeline in production | OCR-markdown → multimodal evolution; reference datasets; field-diff backtests | ~70% automation ceiling; evals gate every change; corrections feed the dataset |
| Ramp (fintech, US) | Receipt processing | Switched to LLM extraction, accuracy improved dramatically | LLMs beat OCR when layouts vary |
| Unstract (IDP platform) | Extraction platform | Dual-LLM "challenge" → null on disagreement | Null > wrong value for machine consumption |
| Reducto / Extend / Iteration Layer (IDP APIs) | Schema-in, JSON-out extraction | Confidence scores + source citations as first-class API fields | Confidence + provenance is table stakes in commercial IDP |
| Skyvern (YC) | Vision browser agent | 85.85% WebVoyager, best on form-filling ("WRITE") tasks | Vision agents win on *unseen* portals; overkill for known forms |
| Browserbase/Stagehand | Managed browsers + AI-Playwright | Action caching, self-healing; $40M Series B | Hybrid deterministic-primary/AI-fallback is the scaling pattern |
| Alma (target company) | Immigration platform | SOC 2 Type I → Type II observation; attorney-led, human-in-the-loop | Review lane is a feature, not a compromise |

Cross-stack patterns: every production team pairs LLM extraction with deterministic validation; every team that scaled built an eval harness before scaling; teams doing browser automation at volume converge on deterministic-primary + AI-fallback + managed browser infra.

## Comparison — Extraction engine (API-first)

| Criterion (weight) | Frontier VLM via ZDR/VPC | Prebuilt ID API (Mindee-class) | IDP platform (Reducto/Extend) | Self-hosted VLM |
|---|---|---|---|---|
| Accuracy on semantic schema extraction (high) | Best (GPT-5.2 / Opus 4.6 / Gemini 3.1 tier) | Good, passports only | Good–best (they route to frontier models) | Good; trails frontier on ambiguous docs |
| Layout robustness without code changes (high) | Native | Per-doc-type models | Native | Native |
| International passports (dealbreaker) | Yes | Yes (Mindee); NO (Textract AnalyzeID) | Yes | Yes |
| Time to production (high, per user) | Days | Days | Days | Weeks |
| PII governance | ZDR/VPC contractual | Extra subprocessor | Extra subprocessor | Strongest |
| Cost at 10k pages/mo (med) | Low (Flash-tier default + escalation) | Per-page fees | Platform premium | Lowest marginal, highest fixed |
| Lock-in / exit | Low (internal interface) | Medium | Medium–high | None |

**Decision: frontier VLM behind a governed endpoint + internal extraction interface.** IDP platforms are the "buy" alternative worth a one-day bake-off if the team wants confidence/citations out of the box; prebuilt ID APIs lose on the G-28 side anyway (they don't do arbitrary legal forms — you'd still need the VLM path, so run one path for both).

## Comparison — Population engine

| Criterion | Deterministic Playwright | + AI fallback (Stagehand/MCP Healer) | Vision agent (Skyvern-class) |
|---|---|---|---|
| Reliability on a known form | Highest | Highest (same primary path) | 12–17 pts lower class |
| Cost per run | ~zero marginal | ~zero after cache warm | Per-step LLM + vision cost |
| Survives target-form drift | Manual fix | Auto-proposed fix, human-approved | Automatic |
| Debuggability | Line-by-line, traces | Same for 95% of path | Agent decision chains |
| When it wins | Known target(s) | Known targets that drift | Many unseen portals |

**Decision: deterministic Playwright now; add the AI-fallback layer when (and only when) target-form drift is observed or targets multiply.**

## Cost model (order-of-magnitude, verify against current price sheets)
Per document (≈2–4 page-images): Flash-tier extraction fractions of a cent to low cents; escalation-tier calls on ~10–20% of documents at a few cents each; dual-model challenge doubles inference on challenged fields only. Reference points: Flash-class OCR ≈ $0.17 per 1,000 pages; premium-model complex docs can reach $0.10–$0.50+/page; self-hosted compute ≈ $0.09 per 1,000 pages (the 167× gap — the exit-ramp economics). Playwright self-hosted ≈ compute only; Browserbase from $20–99/mo if managed sessions are ever needed. At thousands of docs/month the model bill is small against one reviewer-hour saved per day; the real cost center is review labor, which is exactly what the confidence layer optimizes.

## Rollout plan (ASAP path)
**Week 1 — working spine.** FastAPI + Postgres + S3 + Celery/Redis; upload → render → VLM extract (Pydantic schemas, null rule) → validators (FastMRZ + normalizers + name join) → review table → Playwright populate with post-fill verification and submit interlock. This is a demo-able production skeleton.
**Week 2 — production hardening.** Multi-signal confidence + routing; golden set v1 (≥50 labeled docs incl. hard cases) + CI backtest; tracing + dashboards; retention TTL + audit log; DPA/ZDR paperwork moving in parallel (longest lead-time item — start day 1).
**Weeks 3–4 — scale & polish.** Model router (cheap default, accuracy escalation); dual-model challenge; review UI provenance highlighting; correction→dataset loop; load test workers; drift alerts.
**Deferred until triggered:** Temporal migration (long-lived case workflows), AI selector-healing (form drift observed), self-hosted extraction (volume/sovereignty trigger), document-classification layer (multi-doc-type roadmap confirmed).

## 12-Month Outlook
Structured extraction is commoditizing fast: specialized sub-10B open models already beat mid-tier frontier models on schema-JSON, and per-page costs are collapsing — expect the cheap-tier default to keep getting cheaper and the self-hosted exit ramp to keep getting more attractive; the internal extraction interface is what preserves that option. Browser automation is bifurcating into deterministic+managed-infra vs vision agents, with big-tech entries (Chrome Auto Browse, Gemini 3-powered) pressuring independent agent frameworks — another reason not to couple the product to one. If Alma's scale 10×es, this architecture holds; the components that change are queue engine (→ Temporal), extraction backend (→ self-hosted or negotiated committed-use pricing), and review UI sophistication — all behind interfaces designed for it. What would obsolete the recommendation: target systems exposing real APIs (kills the population layer, best possible outcome), or a regulatory change barring external inference on immigration documents (triggers the exit ramp early).

## Recommendation
Build the three-plane pipeline above. Extraction: frontier VLM through ZDR or VPC endpoint (Bedrock/Vertex per existing cloud), Pydantic-schema structured outputs, null-never-guess contract, model-router. Validation: FastMRZ + ICAO checksums + normalizers + cross-doc coherence. Confidence: multi-signal (validators + MRZ agreement + dual-model challenge + image quality), never logprobs alone. Review: field-flagged human queue whose corrections feed the golden set. Population: deterministic Playwright with label/role selectors, post-fill verification, structural submit interlock. Evals: field-level backtests gating every change in CI. Confidence breakdown: **High** on extraction/validation/confidence stack (multiple independent production sources converge); **High** on Playwright-deterministic for known forms; **Medium** on exact model ranking (shifts monthly — the eval harness, not this report, is the durable answer); **Medium** on cost figures (verify current price sheets); **Low→moot** on browser layer longevity (depends on CTO Q3).

## Open questions that gate decisions (for the CTO)
Q1 cost of a wrong field + target automation rate → thresholds, review staffing. Q2 approved vendors + deployment mode (ZDR vs VPC vs none) → extraction endpoint. Q3 browser automation: durable interface or bridge to an API → population investment level. Q4 volume + latency SLO → queue and tier design. Q5 document-type roadmap → classification layer + schema registry now vs later. Secondary: labeled historical docs for golden set; existing cloud/queue/observability; retention & residency requirements; correction feedback loop ownership.

## Risks and Re-evaluation Triggers
Model-version drift silently regressing accuracy → pinned versions + CI backtest gate. Target form changes breaking population → post-fill verification catches it loudly; add healing layer on second occurrence. Review queue becomes the bottleneck → invest in per-field flagging precision before adding reviewers. Vendor outage on the extraction path → second provider pre-integrated behind the internal interface (the router makes this nearly free). Subprocessor addition friction during SOC 2 Type II observation → prefer existing-cloud VPC inference; start paperwork immediately. Cost blowout at scale → escalation-rate dashboard; self-hosted trigger at ~50k pages/mo.
