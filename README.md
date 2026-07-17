# Yunaki — Agentic OS for Law Firms

Deterministic, guardrailed AI for the parts of legal work that can't tolerate hallucination: form extraction, form population, and eligibility screening. This repo is the working build of the first product surface.

---

## 1. What This Repo Is

Upload passport + G-28 → AI vision extraction → editable review table → Playwright populates the target form. A second agentic module, the O-1A/EB-1A eligibility screener, runs a citation-audited assessment with a human-in-the-loop checkpoint.

- **Live demo:** https://mendrika-yunaki.github.io/form-submission/
- **GitHub:** https://github.com/Yugandhar-G/yunaki
- **Validation:** 580/580 fields, 20/20 docs, 3-run eval (98.4%→99.8%→100%)

---

## 2. Architecture

| Layer | Technology | Rationale |
|---|---|---|
| Extraction | Gemini VLM | Deterministic JSON output via Pydantic, temperature 0 |
| Population | Playwright | Surgical form fill, no clicks outside allow-listed selectors |
| Screener | LangGraph + Gemini | O-1A/EB-1A eligibility: deterministic graph skeleton, LLM nodes, HITL interrupt, citation-audited report |
| Frontend | Next.js App Router | Upload UI + review table + `/screener` wizard with live agent feed |
| Backend | FastAPI | Extraction + population + screener endpoints (screener run/review are SSE) |
| Storage | Supabase + local disk fallback | 3-method interface, local-first; screener HITL checkpoints in SQLite |

**O-1A / EB-1A screener (agentic flow):** intake questionnaire + resume/evidence uploads → `compile_matrix` (claims→criteria with citations) → human review interrupt → optional grounded web enrichment (Gemini google_search, injection-guarded) → parallel per-criterion assessment (8 O-1A / 10 EB-1A, USCIS registry as data with 8 CFR refs + RFE patterns) → Kazarian step-2 final merits (EB-1A) → per-visa verdict → deterministic citation audit + constant attorney-review disclaimer. Live SSE activity feed streams the genuine work: actual evidence excerpts being read and Gemini thought summaries token-by-token — nothing templated. Eval harness (`validation/run_screener_validation.py`, 8 personas incl. fabrication bait) hard-fails on any overclaim. See `docs/ARCHITECTURE.md` §Screener.

**Key guardrails:**
- Normalization at extraction time (not fill time): dates → YYYY-MM-DD, country → full English name, state → full name
- Every schema field `Optional` with default `None`. Absent/blank/N/A → `null`, never guess
- Population uses selectors ONLY from `field_map.py` allow-list. Submit/sign/Part 4/Part 5 selectors never in population code
- After filling, read every field back and diff (population report)
- Pydantic validates all LLM output; invalid JSON → one retry → loud failure

---

## 3. Key Technical Decisions

1. **Gemini over GPT-4o/Claude:** Deterministic JSON at temperature 0, Pydantic-enforced schema. Lower cost per extraction at scale.
2. **Temperature 0 + Pydantic:** Forms are deterministic. Hallucination = wrong data on legal form = denial. Zero tolerance.
3. **Normalize at extraction time, not fill time:** Prevents "03/15/1990" vs "1990-03-15" false mismatches.
4. **Playwright over Puppeteer/Selenium:** Debuggable, Python-native, surgical selectors.
5. **Local-first storage:** Demo works without backend. Supabase for production, local fallback for resilience.
6. **3-run eval harness:** 98.4%→99.8%→100% proves convergence. Real regression detection, not one-shot hope.

---

## 4. Market Research: Legal Automation Verticals

### 4.1 Full Ranking (All 15 Verticals)

Scored: Form Volume + Error Severity + Determinism + Competition (inverted) + Yunaki Fit

| Rank | Vertical | Score | Error Rate | Competition | Ship with $0? |
|---|---|---|---|:---:|:---:|
| **1** | **SSDI/SSI Disability** | **23** | **64% initial denial** | **$30M total funding** | ✅ |
| **2** | **Healthcare Insurance Claims** | **21** | **$262B denied/yr** | Fierce (Waystar, AKASA, Experian) | ❌ |
| **3** | **Bankruptcy** | **20** | **48% Ch.13 dismissal** | Low (Best Case legacy, 80% share) | ✅ |
| **4** | **Workers Compensation** | **20** | **40% initial error rate** | **Zero dedicated startups** | ✅ |
| **5** | **Immigration** | **20** | **18% I-864 RFE** | Moderate (LegalBridge, CaseBlink) | ✅ (built) |

### 4.2 SSDI/SSI: The #1 White Space

- **1,937,040 applications in FY 2025** (SSA.gov, scraped)
- **64% denied at initial level** — only 36% approved
- **$30M total venture funding** in entire vertical (Advocate $16.5M, Mindset Care $13M)
- Compare: Personal injury = $500M+, Contracts/CLM = $200M+, Tax = $150M+
- **No dedicated form automation tools** for representatives
- 65% of denials are preventable (wrong dates, missing documents, inconsistent information across forms)
- Average benefit: $1,500+/month. Lost for 6-8 months per denial

### 4.3 Healthcare Claims: The Biggest Market

- **$262B denied annually** (KFF/Medviz, 2023)
- **85% preventable** with better pre-submission processes
- **19% in-network denial rate** — highest since tracking began
- 1.5B+ medical claims/year (highest volume of any vertical)
- 80% of claim denials are deterministic: wrong CPT/ICD codes, missing member ID, demographic mismatch, missing prior auth number

### 4.4 Competition: What Exists and Where They're Weak

| Competitor | Vertical | What They Do | What They Don't Do |
|---|---|---|---|
| **LegalBridge** | Immigration | VLM extraction + intake forms (80+ firms) | Zero validation, zero cross-form consistency |
| **CaseBlink** | Immigration | "Form Filler" (LLM-based) | No guardrails, deterministic checks |
| **DocketWise** | Immigration | Case management + AI bolt-on ("IQ") | No pre-filing validation |
| **Best Case** | Bankruptcy | 80% market share | Legacy desktop, no cross-schedule validation |
| **Manifest OS** | Law Firms | $60M raised, $750M val | Law firm model (capital-intensive) |
| **Waystar/AKASA** | Healthcare RCM | Post-denial processing | Pre-submission guardrails |
| **EvenUp** | Personal Injury | $385M, $2B val | Demand letter generation (generative, not deterministic) |
| **Advocate** | SSDI | $16.5M raised | Intake/navigation, NOT form validation |

### 4.5 Failure Patterns (What NOT to Do)

| Startup | Raised | Why It Died | Lesson |
|---|---|---|---|
| **Atrium** | $75M | Built a law firm + tech company. Economics didn't work. | **Build tools, not law firms.** |
| **ROSS Intelligence** | $15M+ | Sued by Thomson Reuters for using Westlaw data without permission. | **Data rights matter.** |
| **Olive AI** | $1B+ | Healthcare AI "faker" — overpromised, underdelivered. | **Ship product, not marketing.** |

---

## 5. The Strategic Plan: 3-Phase Play

### Phase 1: SSDI Pre-Flight (Month 0-6, $0 Raised)
- Upload: medical records, work history, income docs
- Check: SGA income limit ($1,620/mo non-blind), DLI, onset date, form completeness, cross-form consistency, state DDS rules
- Memory: prior applications, adjudicator patterns, Blue Book matching
- Output: Approval probability + deficiency list
- Revenue: $200-500/check (DIY); $2,000-5,000/year (attorney)

### Phase 2: I-864 Pre-Flight (Month 3-9, parallel track)
- Already built yunaki-doc-autofill tech
- Same architecture, different forms
- Immigration attorneys more tech-forward than disability reps
- Revenue: $50-150/check (DIY); $500-2,000/year (attorney)

### Phase 3: Expand to Validation Platform (Month 6-18)
- Same engine, multiple form verticals: SSDI, I-864, bankruptcy, workers comp, healthcare claims
- Memory layer compounds across all verticals
- Decision point Month 12: raise $2-5M if disability + immigration traction

**Long-term thesis:** "Your claims, your rules, your memory." Every guardrail in this repo — normalization at extraction time, allow-listed selectors, post-fill diff verification, citation-audited screener output — is the same deterministic-core-plus-LLM-edges pattern applied to a different form. That pattern is the product; individual verticals are instantiations of it.

---

## 6. Scraping Methodology & Data Sources

All data verified by live scrape on July 2-3, 2026 using Scrapling v0.4.9.

| Source | Method | Key Data |
|---|---|---|
| ssa.gov/oact/STATS/dibStat.html | Scrapling Fetcher | Disability volumes 2011-2025, 64% denial |
| kff.org | Scrapling Fetcher | 17% in-network denial, 2-49% range by insurer |
| medviz.ai | web_extract | $262B denied, 85% preventable, top 5 triggers |
| donofflutz.com | web_extract | SSDI 64% initial denial, 3x with attorney |
| uscis.gov/i-864p | Scrapling Fetcher | 2026 poverty guidelines (28 table rows) |
| uscourts.gov | Scrapling Fetcher | Bankruptcy filing stats, 48% Ch.13 dismissal |
| va.gov/disability | Scrapling Fetcher | VA disability filing process |
| legalbridge.ai | Scrapling + StealthyFetcher | 34K chars, "80+ firms", no validation |
| manifestos.com | Scrapling + StealthyFetcher | $60M, $750M val |
| caseblink.com | Scrapling StealthyFetcher | "Form Filler" (LLM-based) |
| docketwise.com/pricing | Scrapling Fetcher | 3 tiers, AI bolt-on |
| reddit.com/r/USCIS | web_extract | I-864 RFE patterns, $176K earner RFE |
| abogadolozano.com | Scrapling Fetcher | I-864 household size rules (graph traversal) |

---

## 7. Critical Files in This Repo

| File | Purpose |
|---|---|
| `docs/agent-usage-log.md` | Every subagent prompt + correction, appended chronologically |
| `docs/writeup.md` | Engineering writeup |
| `docs/ARCHITECTURE.md` | System architecture |
| `docs/tech-research.md` | VLM + Playwright research |
| `docs/field-map.md` | USCIS form field selectors |
| `docs/immigration-ai-market-research.md` | Full immigration market deep-dive |
| `docs/all-legal-verticals-market-research.md` | 15-vertical cross-analysis |
| `backend/` | FastAPI backend with extraction, population, schemas |
| `frontend/` | Next.js upload UI + review table |

---

*Last updated: July 17, 2026*
