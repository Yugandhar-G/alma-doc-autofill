# What Can an Agentic OS for Law Firms Be? — Business Thesis

**Date:** July 17, 2026
**Method:** 6 parallel research agents (concept, landscape, workflows, business model, moat, GTM), each followed by an independent adversarial fact-checker that fetched stated sources and tried to refute every quantitative claim. 97 findings produced; 49 web-verified (39 confirmed, 7 corrected, 3 left honestly unverified). Corrections are applied throughout and listed in §10. Repo-internal claims cite file paths. This document obeys the same citation discipline the product enforces: no number without a source, unverified figures labeled as such.

---

## 1. The thesis in one paragraph

An agentic OS for law firms is **a deterministic workflow kernel (code owns the path) + guardrailed drivers (allow-listed access to forms, web, and documents) + a mandatory audit subsystem that can downgrade any AI output + a human-interrupt shell + firm memory — where legal domains install as data packages, not code.** Five of those seven layers already exist in this repo as working, tested primitives. The market discovery is that the "agentic OS" *label* is already taken three times over (Legora aOS, EveOS, Filevine LOIS) — but **every OS claimant ships zero verification architecture**, while courts, bar regulators, and malpractice insurers are simultaneously creating hard external demand for exactly the audit layer this repo has already built. The business value is therefore not the label. It is the open cell in the market matrix: **[solo/small firms] × [consequential government/court filings] × [deterministic audit that can block or downgrade AI output]** — monetized through a billing unit no competitor can copy without rebuilding their architecture: the **audited check**.

---

## 2. What the OS literally is (layer map)

Every clause of the definition maps to shipped code or a named gap ([backend/app/screener/graph.py](../backend/app/screener/graph.py), [citations.py](../backend/app/screener/citations.py), [agent.py](../backend/app/screener/agent.py), [population/field_map.py](../backend/app/population/field_map.py), [storage/base.py](../backend/app/storage/base.py)):

| OS layer | Legal-OS meaning | Status |
|---|---|---|
| **Kernel** | Deterministic graph runtime: fixed edges, pure-function routing, LLM never picks the path, checkpointer injected | **Exists as pattern** (screener graph); gap: no workflow-definition format to load a second workflow without writing Python |
| **Syscalls / drivers** | Guardrailed boundary mediators, each = allow-list + budget + deterministic post-audit (form driver, SSRF-guarded web driver, magic-byte-sniffed document driver) | **Exists** — three drivers already share the contract |
| **Permissions / audit** | Mandatory access control over model output: invalid citations stripped, uncited positive verdicts auto-downgraded, transcript-unseen URLs removed, any overclaim fails CI | **Exists — the strongest layer and the one no competitor has** |
| **Processes** | A matter workflow run: typed state, SQLite-checkpointed, blocking human interrupt(), Send fan-out parallelism | **Exists** (screener); autofill lacks graph-native checkpointing; gap: no isolation (single-tenant, no auth) |
| **Shell / UI** | Review-gate (human-editable table before any consequential action) + SSE activity feed as process monitor | **Exists** |
| **Filesystem / firm memory** | Matter store, cross-matter institutional memory (RFE-pattern recall), tenancy | **Gap** — only the 3-method DocumentStore with raw/final versioning exists |
| **IPC / scheduler** | Multi-workflow orchestration; a cross-matter run queue where pending human interrupts ARE the attorney's work inbox | **Gap** — the reframe "interrupt queue = task list" is the most buyer-legible payoff and requires the matter store first |

**The load-bearing part of the analogy, proven in code:** a new legal domain installs as *data*, not engine code — [criteria.py](../backend/app/screener/criteria.py) (USCIS knowledge as frozen dataclasses with 8 CFR refs and RFE triggers) and [field_map.py](../backend/app/population/field_map.py) (form driver as a declarative tuple). Adding SSDI or I-864 means a new registry + field map + eval persona set while graph, audit, and fill engines stay untouched.

**The fluff part:** "apps run on it / third parties ship packages" is not true today — one hardwired app per plane, no package format, no multi-tenancy. Claiming "platform" before vertical #2 ships repeats the Olive AI pattern in the repo's own failure library. The honest claim: *a deterministic runtime where every workflow inherits checkpointing, human interrupts, driver allow-lists, and a citation audit for free.*

**v1 OS release = 5 items, each a generalization of something already shipped:** (1) kernel services extracted into a shared runtime (checkpoint/interrupt/SSE-bus/citation-audit as a mandatory stage); (2) a workflow-package format, with autofill + screener refactored as the first two packages; (3) matter store with auth/tenancy + first cross-matter memory (RFE/denial outcome recall); (4) per-package tool grants and budgets; (5) a process-table shell where all matters' pending interrupts form one work queue.

---

## 3. The 2026 market map (all figures verified July 2026)

Three camps, none holding the whitespace:

**Camp 1 — BigLaw/enterprise copilots at extreme valuations.** Harvey: $200M at **$11B** (Mar 2026, GIC+Sequoia co-led), ~$190M ARR, 25,000+ custom agents, majority of AmLaw 100 ([harvey.ai](https://www.harvey.ai/blog/harvey-raises-at-dollar11-billion-valuation-to-scale-agents-across-law-firms-and-enterprises)). Legora: $550M Series D at $5.55B + extension to **$5.6B**, $100M ARR ([TechCrunch](https://techcrunch.com/2026/04/30/legal-ai-startup-legora-hits-5-6-valuation-and-its-battle-with-harvey-just-got-hotter/)). Luminance $75M Series C; Spellbook $50M Series B + a $40M RBCx acquisition war chest.

**Camp 2 — plaintiff-PI verticals.** EvenUp ($2B+, $385M raised) launched Pre-Litigation-as-a-Service with its own case-management staff (May 2026, [LawSites](https://www.lawnext.com/2026/05/evenup-extends-beyond-software-with-launch-of-pre-litigation-as-a-service-offering-for-pi-law-firms.html)). Eve ($103M at $1B+) launched **EveOS** (Jun 2026). Filevine ($400M raised) brands itself **"LOIS — Legal Operating Intelligence System."** Supio ($91M) sells "Supio Agent."

**Camp 3 — small-firm incumbents bolting on agents.** Clio ($1B vLex acquisition — largest deal in legal-tech history — + $500M Series G at $5B, [LawSites](https://www.lawnext.com/2025/11/clio-completes-historic-1-billion-vlex-acquisition-announces-500-million-series-g-at-5-billion-valuation-plus-exclusive-interview-with-ceo-and-cfo.html)) made **Clio Work standalone for solos at $199/user/mo** (Apr 2026). Smokeball shipped Archie "agentic reasoning" and a Thomson Reuters CoCounsel partnership. 8am (ex-AffiniPay) partnered with Caseway for **court-form auto-population inside MyCase** — the closest incumbent move onto extract-and-populate turf, with **no published verification layer** ([LawSites](https://www.lawnext.com/2025/07/affinipay-partners-with-canadian-company-caseway-to-bring-ai-court-form-automation-to-mycase.html)).

**Three facts define the opening:**

1. **The "OS" label is crowded but hollow.** Legora launched "aOS — the agentic operating system for legal work" in May 2026; launch coverage contains *zero* discussion of verification, auditability, or accuracy guarantees ([Artificial Lawyer](https://www.artificiallawyer.com/2026/05/07/legora-launches-aos-agentic-operating-system/)). Same for EveOS and Clio Work coverage. The only real verification story in the market is Thomson Reuters CoCounsel (1M users; citation checking against Westlaw) — and it verifies *research citations*, not filings.
2. **"Grounded" ≠ "audited," empirically.** Stanford RegLab's preregistered study: Lexis+ AI hallucinated >17% of queries, Westlaw AI-Assisted Research ~33%, while both vendors marketed hallucination-free systems ([Stanford HAI](https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries)). LLRX now runs a public tracker of vendor hallucination-marketing claims (May 2026).
3. **The sanctions wave quantifies the pain.** Damien Charlotin's database hit **1,598 court decisions involving AI-hallucinated material by June 9, 2026, growing ~8 cases/day**, ~800 in US courts ([damiencharlotin.com/hallucinations](https://www.damiencharlotin.com/hallucinations/)). Adoption is outrunning governance: 79% of legal professionals use AI but 43% of firms have no AI policy; mid-sized firms use AI "extensively" at 93% vs 10% of small firms ([NC Bar / Clio LTR / 8am reports](https://www.ncbar.org/nc-lawyer/2026-05/by-the-numbers-what-surveys-show-about-law-firm-ai-adoption/) — aggregated across surveys; check primaries before external use).

**The whitespace:** nobody sells audited determinism for consequential filings to solo/small firms. (Negative-existence claim — no counterexample found across 23 verified competitor checks, but unprovable in principle; treat as "none found," not "none exists.")

**The window:** real but closing on a 12–24 month horizon, driven by incumbent down-market moves (Clio Work standalone, 8am/Caseway, TR-Smokeball syndication) — none has a verification layer today, but any could add a read-back diff faster than a startup builds distribution. Consequence: **make the audit layer the product; form-filling is being commoditized.**

---

## 4. Why it's defensible (moat ranking, attacked and ranked by realism)

External forcing functions arriving *now*:
- **Courts:** 57 federal district-court AI standing orders (86 orders requiring verification across federal + state; trace.law counts ~113 active) ([legalaigovernance.com tracker](https://legalaigovernance.com/tracker/court-orders/)). Judge Starr's N.D. Tex. certification order is the template.
- **Bar ethics:** ABA Formal Opinion 512 (July 29, 2024) established a verification duty for GAI output scaling with stakes ([ABA](https://www.lawnext.com/wp-content/uploads/2024/07/aba-formal-opinion-512.pdf)).
- **Insurers:** EPIC survey — 7 of 13 LPL insurers reported increased AI-related claims, first year underwriters saw actual claims; CNA runs a supplemental AI questionnaire (tools, written policy, output-verification process). AI exclusions exist so far only in E&S/manuscript forms (Hamilton Select broadest); no major admitted carrier had filed one as of May 2026 ([Insurance Business](https://www.insurancebusinessmag.com/us/news/professional-liability/ai-liability-claims-emerging-in-lawyers-eando-market-epic-survey-finds-580124.aspx)).
- **Cross-industry:** CSA/Aembit March 2026 — 68% of organizations cannot distinguish AI-agent actions from human actions in audit logs ([CSA](https://cloudsecurityalliance.org/press-releases/2026/03/24/more-than-two-thirds-of-organizations-cannot-clearly-distinguish-ai-agent-from-human-actions)); EU AI Act high-risk logging obligations apply from August 2, 2026.

Moat candidates, ranked:

1. **Citation audit as compliance artifact** (real today). The audit output — which refs were stripped, which verdicts downgraded, human-review timestamps, post-fill read-back diff — maps almost one-to-one onto what court certifications and insurer questionnaires ask an attorney to attest. Honest limits: no court accepts a vendor log as satisfying the attorney's personal duty (it *supports* the certification), and the audit verifies **provenance, not truth** — it catches fabrication, not bad judgment. Say exactly that.
2. **Eval harness as trust substrate** (highest ceiling, conditional). `run_screener_validation.py` exits 0 only at zero overclaims — an inversion no vendor markets. But a private harness is just another vendor claim; the play is to **publish the methodology and get it third-party validated** (Vals AI's VLAIR benchmark, first published Feb 2025, proves buyers respond to independent legal-AI benchmarks). The audit *technique* won't stay proprietary (HalluGraph, [arXiv 2512.01659](https://arxiv.org/abs/2512.01659), is already academizing it) — the race is to institutionalize the standard, not keep a secret.
3. **OS switching costs** (real but prospective — near zero today; they materialize when checkpointed matter state and audit history acquire external referents like insurer filings; sharpest OS-vs-copilot argument: a chat window accumulates nothing).
4. **Criteria-registry-as-data** (expansion leverage, not a moat — a module is copyable in days; the harness that validates all modules is the scarce asset; value = vertical N+1 ships in weeks).
5. **Firm-memory flywheel** (weakest — a data asset, not a network effect, at small-firm volume; claiming "network effects" in a deck would fail the product's own overclaim test; cross-firm pooling is a year-2+ option gated on MSA data-rights language).

Moats 1+2 are one composite: **compete on provability.** Point tools compete on output quality, copilots on convenience. Following this play requires incumbents to publish a methodology under which their own products currently fail — an innovator's-dilemma bind, not just an engineering task.

Failure-library design constraints (each verified): **Atrium/Clearspire** → sell the engine, don't drive the taxi (gates the ABS fork). **ROSS** → data rights in the first MSA; registry stays sourced from public regulation only. **Olive AI** (raised ~$832–856M at a $4B peak valuation, shut down Oct 31, 2023 — *not* "$1B+ raised" as previously logged; [Healthcare Dive](https://www.healthcaredive.com/news/olive-ai-shuts-down/698455/)) → ship the proof, not the adjective; never say "hallucination-free." **Gavelytics** → every vertical must have standalone unit economics — the strongest internal argument for the OS framing. New 2026 entry: **Robin AI** — failed ~$50M raise, HMRC winding-up petition, distressed sale; Microsoft acqui-hired ~18 engineers and explicitly stated it has *no plans to acquire* the company ([Legal IT Insider](https://legaltechnology.com/2026/01/12/microsoft-hires-raft-of-robin-ai-engineers-to-bolster-its-word-team/)) — a mid-tier horizontal copilot with no moat against incumbents.

---

## 5. What the OS orchestrates next (workflow census)

The repo's 5-factor rubric (volume, error severity, determinism, competition-inverted, fit; max 25) extended from forms to the 14-stage firm lifecycle. Three workflows tie at **22/25, all beating the form-prep baseline (21)**:

| Rank | Workflow | Why | Anchor stats |
|---|---|---|---|
| 1 | **Document-gathering completeness** | Extends existing upload/extraction with a per-matter-type checklist + deterministic diff; the SSDI research already marks every completeness check "no current tool" | SSDI denial triggers are dominated by insufficient/missing evidence ([docs/all-legal-verticals-market-research.md](all-legal-verticals-market-research.md) §3.2) |
| 2 | **Pre-filing validation ("Pre-Flight")** | The read-back-diff verifier generalizes to court/agency rulesets; roadmap already uses the name | ~3.7% of e-filings rejected on average (industry estimates to ~12%); causes: filing-procedure 45%, document-format 26%, incorrect data 22%, filer request 7% — vendor-published data ([File & ServeXpress](https://www.fileandserve.com/why-was-my-filing-rejected/)) |
| 3 | **Inbound RFE/deficiency-notice triage** | Reuses extract → classify → deadline-pull → cited response checklist → HITL end-to-end; near-zero dedicated competition; closes the lifecycle loop | ABA malpractice profile: >1/3 of claims stem from administrative errors + client-relations failures combined ([WSBA summary](https://nwsidebar.wsba.org/2020/10/22/risk-management-by-the-numbers-new-aba-study-on-malpractice-claims/)) |

Also scored: conflict check 20 (cheapest credibility feature: fuzzy match + approve/waive gate); deadline/docketing 20 but **integrate-don't-build** (LawToolBox/CalendarRules own the rules corpus); engagement letters 18 (bundle with conflict check as one "matter-opening" node). Lowest: drafting 12, document review 14, knowledge management 11 — *exactly where Harvey/CoCounsel/Spellbook capital is concentrated*. The rubric independently reproduces the core thesis: **own the deterministic stages, orchestrate around the judgment-heavy ones** (expose drafting as a pluggable slot).

**The OS argument is the composition:** the high scorers are contiguous — intake/screener → conflicts → engagement → gather/completeness → extract → review → populate → pre-flight → file → docket → track → notice triage → loop. Every consequential transition maps onto an existing primitive (interrupt(), deterministic routing, downgrade audits, checkpointed state, SSE feed). **The moat is the checkpointed state machine spanning stages, not any single stage tool.** Economic frame: Clio 2025 benchmarks — utilization 38% (3.0 billable hours/8-hr day), realization 88%, collection 93%, 93-day median lockup ([Clio](https://www.clio.com/resources/legal-trends/benchmarks/)) — the OS's ROI denominator is the ~5 non-billable hours/day it absorbs, and the scheduler's KPI is review-seconds-per-document (attorney minutes are the scarce resource the OS allocates).

---

## 6. Business model

**Pricing anchors (verified):** Clio $49–149/user/mo (AI gated to top tiers); Docketwise $69/$99/$119 (IQ = writing-assistance bolt-on at Pro); Paxton $499/user/mo self-serve — proof solos pay ~$6K/yr/seat; Harvey est. ~$1,200/seat with ~20–25-seat minimums (unofficial estimates) — structurally irrelevant to small firms; only 3 of 10 legal-AI vendors publish a per-seat price ([vaquill benchmark](https://www.vaquill.ai/blog/legal-ai-pricing-benchmark)). EvenUp per-demand price points circulate only in competitor blogs — **unverified; do not quote.** The proven outside-legal template: **Intercom Fin at $0.99 per verified resolution, never billed when the procedure fails** ([fin.ai/pricing](https://fin.ai/pricing)).

**The OS's native billing unit — the audited check.** One billable event = a workflow run that passed the deterministic audit: zero overclaims, clean field diff. It is customer-auditable (unlike token/credit meters), already machine-defined by [citations.py](../backend/app/screener/citations.py) + the read-back diff + the CI gate, mirrors Fin's never-bill-on-failure rule (a downgraded run is free), and **cannot be copied by a writing-assistant competitor without rebuilding the audit layer — the pricing model encodes the moat.** No player in these verticals publishes transparent, self-serve, outcome-metered pricing for verified filings; publishing it is simultaneously a GTM wedge and a moat signal.

**Three-layer architecture:** (1) platform seat at/below Docketwise Basic ($69) — review-gate UI, storage, feed, base audit trail; (2) vertical workflow modules as installable apps in the README's own bands (SSDI $2–5K/yr, immigration $500–2K/yr attorney tiers) with N checks included; (3) metered audited-check overage (README DIY bands: $200–500 SSDI, $50–150 I-864). Premium compliance tier: exportable masked traces, per-filing audit certificates, eval-report access — gated the way enterprise SaaS gates SSO/audit logs, positioned as malpractice-defense collateral.

**Scenarios (arithmetic from sourced inputs; conversion rates are labeled assumptions):**
- **A — SSDI point tool:** buyer universe 46,575 (43,620 attorneys + 2,955 EDPNAs, [docs/vertical-expansion-leads.md](vertical-expansion-leads.md)); at $3,500/yr midpoint: 100 accounts = $350K ARR; 1% penetration = ~$1.63M ARR. Full-penetration ceiling ≈ **$163M — too small alone for venture outcomes.** That ceiling is the argument for the platform.
- **B — OS platform, 2 modules live (Mo. 18–24):** 250 firms × (2 seats @ $79/mo + 1.5 modules @ $1,500/yr) ≈ **$1.04M ARR** — roughly double per-account revenue vs the point tool at identical logo count, plus expansion revenue without new logos: the metric a seed raise is underwritten on.
- **C — services entity:** SSA caps rep fees at lesser of 25% of back pay or **$9,200** per favorable decision (unchanged into 2026; $123 user fee deducted; [Federal Register](https://www.federalregister.gov/documents/2025/05/06/2025-07813/maximum-dollar-limit-in-the-fee-agreement-process-partial-rescission)). High per-unit revenue, contingent, back-pay-funded, slow cash, 64% initial denial.

**Month-12 fork verdict:** take the **$2–5M SaaS raise** — the OS story *is* the module-expansion story, and an owned services entity collapses it into the Atrium pattern. Material new fact the fork framing was missing: **SSDI representation is federally open to non-attorneys (EDPNAs), so the services route for the beachhead vertical never required Arizona ABS at all** (151 ABS licenses exist incl. KPMG if ever needed for attorney-required verticals; [ASU Law Journal](https://arizonastatelawjournal.org/2026/01/27/arizonas-alternative-business-structures-innovation-meets-neighboring-resistance/)). Recommended hybrid: sign one ABS or EDPNA rep-org as a **design partner paying per audited check** — services-side proof and unit economics without owning the liability.

---

## 7. Top 3 business-value plays (scored: revenue potential / defensibility / time-to-proof / capital fit)

| Play | Shape | Score | Verdict |
|---|---|---|---|
| **1. The Audited Filing Platform** | Land small-firm immigration form-prep → week-6 screener switch-on → publish audited-check pricing + eval methodology → completeness & Pre-Flight modules → SSDI module → $2–5M raise on expansion metrics | High / High / Fast / Seed-sized | **Recommended — the company** |
| 2. Trust-substrate-as-infrastructure | White-label the guardrailed runtime under Paradigm / Mitratech INSZoom (6–12 mo window from Jun 2026) / ALSP brands; "a guardrailed extract-review-populate runtime you can embed" | Med / Med / Med / cheap | **Run as a channel, not the company** (dependency risk; builds fewer moats; fastest paying usage via ALSPs) |
| 3. Services capture (EDPNA rep-org / ABS) | Own the representative, capture $9,200-capped fees, tech as internal margin | High per-unit / Low / Slow / heavy | **Design-partner licensee only** — the Atrium trap as an owned entity |

**Recommended 12-month sequence for Play 1** (extends the existing roadmap, doesn't replace it):
- **Now–Sept 16** (AILA early-bird deadline — nearest hard GTM date): wave-1 design partnerships with the 4 HOT immigration leads (free 90-day, measured before/after, reference); demo = live extract-review-diff on the prospect's own documents + the 580/580 validation result. Fix the 3 phantom-collision lines in client-prospect-research.md; run USPTO clearance on "Yunaki."
- **Oct 2026:** AILA Atlanta (Oct 15–16) for the land motion; ClioCon Boston (Oct 26–27) for the platform story and App Directory listing (250+ integrations; Clio has no immigration form engine). NOSSCR Salt Lake City is **Oct 13–16** (repo's San Diego date was the 2025 event) — attend only if an SSDI Pre-Flight demo exists by mid-September.
- **Mo. 3–6:** wave-2 paid pilots (~23 proven-software-buyer warm firms) at Docketwise-anchored pricing; screener contractually switched on at week 6 of every pilot; **publish the eval methodology and submit to a third-party benchmark (VLAIR-style) before someone else defines "fabrication gate."**
- **Mo. 6–12:** ship v1 OS items 1–3 (shared runtime, package format, matter store + tenancy); doc-gathering completeness module; I-864 or SSDI module as the second data package (proves vertical N+1 in weeks); sign the per-audited-check design partner; instrument **time-to-second-workflow as the north-star metric** — it is literally the moment the point tool becomes an OS.
- **Mo. 12:** raise $2–5M on: expansion revenue per logo, time-to-second-workflow, published zero-overclaim track record, and the module-economics story.

**GTM doctrine (from the GTM lane):** two vocabularies, one product. Small firms buy outcomes — "zero-defect filings," "nothing files without your review," "most RFEs are triggered by missing documents and filing errors, not eligibility problems" ([CitizenPath, verified verbatim](https://citizenpath.com/rfe-request-for-evidence-immigration/)). "Agentic OS" is for partners, investors, and ClioCon-stage thought leadership only. The buyer's objection is trust, not awareness: AILA 2025 shows 68% personal GenAI use (verified) while firm-level adoption lags dramatically (the specific ~17% figure could not be re-verified — the direction is corroborated by 8am 2026: 69% individual vs 34% firm-level legal-specific adoption). The OS sale is a *discovery, not a pitch*: the trigger is the first cross-workflow audit-trail answer ("show me every field a human edited before filing, across all matters, this month") or watching workflow #2 go live in a day with zero re-onboarding.

Displacement ammunition (verified): Docketwise/Manji case study — "removed 70% of my immigration forms work"; eImmigration/Canero — "300% faster form preparation," 10 hours of manual prep to under two (~75–80% reduction; the previously logged "65%" figure was wrong); the dominant incumbent's 2025 breach exposed exactly 116,666 immigration records → "local-first, no PII in logs, content-hash references" is a wedge, not a footnote.

---

## 8. The name-collision finding (resolves an open blocker)

**The tryyunaki.com collision is a phantom.** The domain does not resolve; no funded company named Yunaki exists. The real entity behind every attribute in the repo's research ($5.1M from Bling/Forerunner/Village Global/NFX/Conviction/MVP/NEA/Silkroad; immigration AI; corporate lane) is **Alma (tryalma.com)** — an AI-plus-attorneys immigration *law firm* founded Oct 2023 ([TechCrunch](https://techcrunch.com/2024/07/11/immigration-visa-alma-law/)). The repo's own alma→yunaki rebrand (commit 54468f1) find-and-replaced the competitor's name inside [docs/client-prospect-research.md](client-prospect-research.md) (lines 14, 153, 191 — the only unsourced claims in that doc), manufacturing the phantom. **The rename WAS the collision fix.** Actions: correct those 3 lines to name Alma; keep Alma on the corporate-lane watchlist (different buyer — it sells legal services to companies; Yunaki sells software to firms); its funding actually validates that top-tier VCs fund the tech-enabled-firm structure contemplated in the fork. Remaining diligence: USPTO clearance + domain ownership before corporate outreach.

---

## 9. Risks and kill criteria

| Risk | Signal to watch | Response |
|---|---|---|
| Incumbent adds a verification layer (8am/Caseway, Clio Work) | A read-back-diff or citation-audit feature announcement | Accelerate methodology publication + third-party validation; the standard, once external, is the moat they can't ship overnight |
| "Fabrication gate" gets defined by someone else | VLAIR or an incumbent publishes a competing audit standard | 6–12 month window per the moat lane; publishing first is the whole game |
| Point-tool trap (Gavelytics) | A vertical module that can't be revenue-positive standalone | Kill the module, keep the harness; platform investment only as measured reduction in vertical launch cost |
| Trust-substrate claim decays into marketing (Olive) | Any external claim not of the form "zero overclaims across N personas under a published methodology" | Hard rule already in CI; extend to marketing review |
| Services gravity (Atrium) | Pilot firms saying "just do it for me" | Route to the design-partner licensee; never own the firm before per-matter margin is proven with the tool |
| Data-rights failure (ROSS) | Any training/eval use of customer edits without MSA language | Opt-in clause in first MSA; no cross-firm pooling without separate consent |
| October event pileup | NOSSCR Oct 13–16 vs AILA Oct 15–16 vs ClioCon Oct 26–27 | Committed: AILA + ClioCon; NOSSCR only with an SSDI demo by mid-Sept |

---

## 10. Corrections registry (verification pass outcomes)

Facts the adversarial pass corrected — now the defensible versions:
1. **tryyunaki.com collision** → phantom; real competitor is Alma/tryalma.com (§8).
2. **Olive AI "raised $1B+"** → raised ~$832–856M at a $4B peak valuation; shut down Oct 31, 2023.
3. **"Microsoft acquired Robin AI"** → false; acqui-hired ~18 employees, explicitly no acquisition plans.
4. **E-filing rejection causes** → per source: filing-procedure 45%, document-format 26%, incorrect data 22%, filer request 7% (sub-issues: clerical 11%, incomplete docs 9%).
5. **"100+ federal standing orders / ~25 requiring certification"** → tracker shows 57 federal district orders; 86 requiring verification across federal+state; ~113 active total (trace.law).
6. **"Insurers inserting AI exclusions"** → only E&S/manuscript forms so far; no major admitted LPL carrier as of May 2026. Questionnaires and first claims: confirmed.
7. **eImmigration "65% form-prep reduction"** → source publishes "300% faster" / 10 hrs → <2 hrs.
8. **NOSSCR 2026** → Salt Lake City Oct 13–16 (San Diego Sept 9–12 was the 2025 event).
9. **Trust-account "leading cause of discipline"** → defensible framing: ~4% of grievances (overdrafts), ~10% of cited violations (WSBA data); "leading cause"/"commingling most common" not supported by primary sources.
10. **Left unverified (do not use without further sourcing):** EvenUp per-demand price points; AILA ~17% firm-level adoption; "no vendor ships a CI fabrication gate" (negative-existence — "none found" only); Clio Duo strictly-Complete-tier gating.

---

## 11. Bottom line

The great business value discovered: **the audit layer is the company.** The market spent 2025–26 proving three things at once — that "agentic OS" branding sells (three funded companies adopted it), that nobody attached verification architecture to it, and that courts, bar regulators, and insurers are creating mandatory demand for machine-checkable verification of AI legal work. This repo already owns the only hard asset that matters for that demand: a deterministic audit that can overrule the model, and a CI harness that proves it. The play is to sell that as a compliance artifact today (land: immigration Pre-Flight), publish the methodology before the standard gets defined by someone else, price the product in the unit only this architecture can meter (the audited check), and let each new vertical install as a data package on the same runtime — so that by Month 12 the pitch to investors is not "we automate forms" but "we operate the audited runtime that legal AI work has to run on to be insurable, certifiable, and filed."
