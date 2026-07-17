# Deep Dive: Extraction + Population
## For Yunaki Interview — Clean Flow

---

## Overview

Two AI-powered pipelines connected by a human review step:

**Pipeline 1: Extraction** — Image → Structured Data
**Pipeline 2: Population** — Structured Data → Filled Form

Human review sits between them.

---

## Deep Dive 1: Extraction Pipeline

```
User uploads file
        │
        ▼
┌───────────────┐
│ Render        │
│ PDF → images  │    220 DPI per page
│ Image → load  │    EXIF orientation corrected
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ Quality Gate  │
│               │
│ • Short side  │    Reject before AI call
│   ≥ 500 px    │    Cheaper than VLM failure
│ • Laplacian   │
│   variance    │    Variance < 40 → blurry
│   ≥ 40        │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ Gemini Call   │
│               │
│ • Structured  │    response_schema = Pydantic model
│   JSON        │    Temperature = 0
│ • response_   │    Model enforces schema at API level
│   mime_type   │
│   = json      │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ Validation    │
│               │
│ • Dates →     │    03/15/1990 → 1990-03-15
│   YYYY-MM-DD  │
│ • CA →        │    Abbreviation → full name
│   California  │
│ • USA →       │    Variant → canonical
│   United      │
│   States      │
│ • N/A stays   │    Never guess
│   null        │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ Coherence     │
│               │
│ Passport name │    If both docs uploaded,
│ ↔ G-28 name  │    compare surname + given_name
│               │    Fuzzy match, 85% threshold
│               │    Warning only, never block
└───────┬───────┘
        │
        ▼
   ExtractionEnvelope
   (data + warnings)
```

**The key insight:** The VLM does exactly one thing — read an image and return structured JSON. Everything after that is deterministic Python. If the VLM fails, we catch it before it reaches the user.

### What Happens When the VLM Fails

**Case 1: Invalid JSON**
```
Gemini returns malformed JSON
        │
        ▼
Retry once (same model)
        │
        ├── Success → continue
        └── Fail → RuntimeError + source hash
                  (error message never contains extracted values)
```

**Case 2: All fields null or wrong document type**
```
First model (flash) returns null-heavy or wrong detection
        │
        ▼
Escalate to stronger model (pro)
        │
        ├── Success → continue
        └── Fail → RuntimeError + source hash
```

**Case 3: Quality gate rejects the image**
```
Blur scan uploaded
        │
        ▼
Rejected before AI call
        │
        ▼
"Please re-scan — image too blurry"
```

This is the guardrail architecture: fail fast, fail loudly, never let bad data through silently.

---

## Deep Dive 2: Population Pipeline

```
User confirms review
        │
        ▼
┌───────────────────┐
│ Playwright Launch │
│                   │
│ • Headless = PDF  │    Headless captures PDF artifact
│ • Headed = PNG    │    Headed captures screenshot
│ • Timeout budget  │    60s total, derived from config
│   derived from    │    No magic numbers
│   field count     │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Write Pass        │
│                   │
│ For each FieldSpec│    FIELD_MAP = allow-list
│ in FIELD_MAP:     │    Only these selectors get touched
│                   │
│ 1. Resolve source │    passport.surname → "Garcia"
│ 2. Skip if null   │    Null never reaches the form
│ 3. Apply action   │    fill / select / check
│ 4. Record intent  │    "I intended to write 'Garcia'"
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Verify Pass       │
│                   │
│ For each FieldSpec│
│ in FIELD_MAP:     │
│                   │
│ 1. Read back DOM  │    input_value() or is_checked()
│ 2. Diff against   │    What we wrote vs what's there
│    intent         │
│ 3. Assign status  │
│                   │
│ • filled         │    Match
│ • skipped_null   │    No data to write
│ • mismatch       │    DOM ≠ intent
│ • error          │    Something broke
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Artifact Capture  │
│                   │
│ • Headless → PDF  │    CDP printToPDF, print_background
│ • Headed → PNG    │    Full-page screenshot
│ • Content hash ID │    SHA-256, PII-safe
└─────────┬─────────┘
          │
          ▼
   PopulationReport
   + artifact download
```

### Why Read-Back Verification?

Because browsers are not reliable writers.

```
Write: "California" into #state dropdown
        │
        ▼
DOM might actually hold: "CA" (the value, not the label)
        │
        ▼
Read-back catches the mismatch
        │
        ▼
Report: "mismatch — intended California, actual CA"
```

Other reasons:
- JavaScript resets fields after we write
- Sticky headers overlay inputs
- CSS transitions show one value while DOM holds another
- Dropdown value ≠ dropdown label (exact problem in the G-28)

The read-back is the safety net. Without it, we'd be trusting the write, which is the wrong thing to trust in a browser.

### The FIELD_MAP Allow-List

The population plane can only touch selectors explicitly listed. Reasons:

**Duplicate-id trap:** First Name(s) and Middle Name(s) both have `id="passport-given-names"`. Without explicit disambiguation, a generic selector fills the wrong field.

```
FieldSpec(
    selector='input[name="passport-given-names"]',
    source="passport.given_names",
    nth=0    ← first match
)
FieldSpec(
    selector='input[name="passport-given-names"]',
    source="passport.middle_names",
    nth=1    ← second match
)
```

**Dropdown value vs label trap:**
```
State dropdown: option values are "CA", "NY"... labels are "California", "New York"
→ select_option(label="California") not select_option("CA")

Sex dropdown: values are "M", "F", "X"
→ select_option("M") not select_option(label="Male")
```

The FIELD_MAP encodes all these traps as comments next to the selector. No wiki, no separate documentation — the trap and the fix live in the same line.

---

## Connecting the Two Pipelines

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (Next.js)                     │
│                                                             │
│  Step 1: Upload files                                      │
│  Step 2: See extraction results (editable table)           │
│  Step 3: Confirm and populate                              │
│  Step 4: Download artifact                                 │
└──────┬──────────────────────────────────────────┬───────────┘
       │                                          │
       │ POST /api/extract                       │ POST /api/populate
       ▼                                          ▼
┌──────────────────┐                    ┌──────────────────┐
│ Extraction       │                    │ Population        │
│ Pipeline         │                    │ Pipeline          │
│                  │                    │                   │
│ Render → Quality  │                    │ FIELD_MAP resolve │
│ Gate → Gemini     │───────────────────►│ → Write → Verify  │
│ → Validate →     │   (user review &   │ → Artifact        │
│ Coherence         │    edit in between)│                   │
└──────────────────┘                    └──────────────────┘
       │                                          │
       ▼                                          ▼
┌──────────────────┐                    ┌──────────────────┐
│ ExtractionEnvelope│                    │ PopulationReport  │
│ (JSON in DB)      │                    │ (JSON in DB)      │
└──────────────────┘                    └──────────────────┘
```

**The human review step is the bridge.** The AI doesn't go straight from extraction to population. The user sees the structured data, edits it, and confirms. This means:
- If the VLM extracts wrong data, the user catches it before it hits the form
- If the user corrects the data, the corrected value flows into population
- The system is safe-by-design, not safe-by-perfect-AI

---

## What to Drill Into

If they ask for detail on one component, these are the areas:

| Component | Detail to Discuss |
|---|---|
| **Extraction** | Why temperature 0, Pydantic schema enforcement, model escalation logic |
| **Quality gate** | Laplacian variance, why reject before AI call (cost + speed) |
| **Normalization** | Why at extraction time (not fill time), prevents format mismatches |
| **Coherence** | Why fuzzy match with warnings (not hard blocks), 85% threshold |
| **FIELD_MAP** | Allow-list pattern, duplicate-id trap, dropdown value/label trap |
| **Read-back** | Why browsers aren't reliable writers, four statuses, `ok` flag semantics |
| **Artifact** | Headless PDF vs headed PNG, content hash IDs, PII safety |
| **PII** | Three-tier policy: never log, hash only, can log |

Pick two and be ready to go 5 minutes deep on each.

---

*This is the complete deep dive. Two pipelines, one review step, clear boundaries between AI work and deterministic code.*
