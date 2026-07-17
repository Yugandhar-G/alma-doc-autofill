# YUNAKI System Mastery — Interview Prep Document
## Every Component, Decision, Edge Case, and Tradeoff

**Prepared:** July 6, 2026  
**For:** Yugandhar Gopu — Yunaki Product Engineer (AI) interview, July 9

---

## TABLE OF CONTENTS

1. [Architecture Overview](#1-architecture-overview)
2. [Extraction Plane (Deep Dive)](#2-extraction-plane-deep-dive)
3. [Population Plane (Deep Dive)](#3-population-plane-deep-dive)
4. [Storage Plane](#4-storage-plane)
5. [Observability Plane](#5-observability-plane)
6. [PII / Security Model](#6-pii--security-model)
7. [Schema Design](#7-schema-design)
8. [Testing & Evaluation](#8-testing--evaluation)
9. [Frontend Flow](#9-frontend-flow)
10. [Design Decisions & Rationale](#10-design-decisions--rationale)
11. [Edge Cases Handled](#11-edge-cases-handled)
12. [What I'd Change With Hindsight](#12-what-id-change-with-hindsight)
13. [How to Extend This System](#13-how-to-extend-this-system)
14. [Likely Interview Questions & Answers](#14-likely-interview-questions--answers)

---

## 1. ARCHITECTURE OVERVIEW

### High-Level Data Flow

```
User uploads images/PDFs
         │
         ▼
┌─────────────────────────────────────────────────────┐
│                   FASTAPI BACKEND                    │
│                                                      │
│  ┌───────────┐    ┌───────────┐    ┌─────────────┐ │
│  │ /api/extract │   │ /api/populate │  │ /api/telemetry │ │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘ │
│         │                  │                   │       │
│  ┌──────▼──────────────────▼───────────────────▼──────┐│
│  │                    MAIN APP                        ││
│  │  ┌─────────────┐  ┌──────────────┐  ┌───────────┐ ││
│  │  │ _read_capped │  │ _save_guarded │  │ coherence │ ││
│  │  │ (size guard) │  │ (storage)    │  │ warnings  │ ││
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬─────┘ ││
│  └─────────┼─────────────────┼─────────────────┼───────┘│
│            │                 │                 │        │
│  ┌─────────▼──────┐  ┌──────▼──────────┐  ┌──▼───────┐│
│  │ EXTRACTION     │  │ POPULATION      │  │STORAGE   ││
│  │ PLANE          │  │ PLANE           │  │          ││
│  │                │  │                 │  │          ││
│  │ render.py      │  │ field_map.py    │  │base.py   ││
│  │ quality.py     │  │ fill.py         │  │          ││
│  │ validators.py  │  │ verify.py       │  │local_store│
│  │ coherence.py   │  │ artifact.py     │  │supabase  ││
│  │ prompts.py     │  │                 │  │          ││
│  │ engine.py      │  │                 │  │          ││
│  └────────┬───────┘  └──────┬──────────┘  └──────────┘│
│           │                 │                         │
│  ┌────────▼───────┐  ┌─────▼─────────────────────────┐│
│  │ Gemini VLM     │  │ Playwright Browser            ││
│  │ (structured    │  │ (form fill + verify)          ││
│  │  JSON output)  │  │                                ││
│  └────────────────┘  └────────────────────────────────┘│
│                                                      │
└──────────────────────────────────────────────────────┘
         │                         │
         ▼                         ▼
┌──────────────────┐    ┌──────────────────┐
│  SUPABASE /      │    │  LANGfUSE        │
│  LOCAL DISK      │    │  (observability) │
│  (storage)       │    │  (tracing)       │
└──────────────────┘    └──────────────────┘
         │
         ▼
┌──────────────────┐
│  FRONTEND        │
│  (Next.js)       │
│  Upload + Review │
└──────────────────┘
```

### Component Counts

| Component | Files | Lines | Purpose |
|---|---|---|---|
| Extraction plane | 6 | ~800 | Render pages, quality gate, VLM call, validate, normalize, coherence |
| Population plane | 4 | ~500 | Field map, fill, verify, artifact capture |
| Storage plane | 3 | ~200 | Abstract store, local disk, Supabase |
| Observability | 1 | ~220 | Langfuse tracing, PII masking |
| Schemas | 3 | ~130 | Pydantic contracts for extraction + population + API |
| API layer | 1 | ~330 | FastAPI routes, upload guards, lifecycle |
| Tests | 8 | ~500 | Golden extraction, population, validators, coherence |
| Frontend | 10+ | ~800 | Next.js App Router, review table, upload flow |

---

## 2. EXTRACTION PLANE (DEEP DIVE)

### File: `engine.py` — The Heart of Extraction

**Entry point:** `extract_document(file_bytes, filename, doc_type) → ExtractionEnvelope`

**Flow:**
1. Compute `source_hash = SHA256(file_bytes)` — PII-safe identity for the document
2. `render.prepare_pages()` → list of PIL Images (PDF pages rendered at 220 DPI, or single image)
3. `assert_page_quality()` per page — **quality gate BEFORE any LLM call** (resolution + blur)
4. `render.to_png_bytes()` → PNG bytes for each page
5. `_call_gemini()` → structured extraction with retry
6. Empty/null check → **escalate to stronger model** if needed
7. Wrong document detection → `document_type_detected` field
8. Post-validation (`validate_passport` or `validate_g28`) → deterministic normalization
9. Cross-document coherence check (passport ↔ G-28 name match)
10. Build `ExtractionEnvelope` with data, warnings, model_used, source_hash

### File: `engine.py` — Gemini Call & Retry

```python
# Key design: response_mime_type="application/json" + response_schema=wrapper
config = genai_types.GenerateContentConfig(
    temperature=settings.extraction_temperature,  # 0.0 — deterministic
    response_mime_type="application/json",
    response_schema=wrapper,  # Pydantic model → Gemini enforces structure
)

# Retry loop (max_retries=1 → 2 attempts total)
for attempt in range(1, attempts + 1):
    response = await client.aio.models.generate_content(
        model=model, contents=[prompt, *parts], config=config
    )
    parsed = response.parsed
    if isinstance(parsed, wrapper):
        return parsed
    # Fallback: validate JSON manually
    try:
        return wrapper.model_validate_json(response.text or "")
    except (ValidationError, ValueError):
        # Log field-level errors, NOT input values (PII rule)
        issues = [(e["loc"], e["type"]) for e in exc.errors(include_input=False)][:5]
```

**Key insight:** `response.parsed` is the structured output when Gemini returns valid JSON matching the schema. The fallback `response.text` handles cases where parsing fails at the SDK level.

### File: `engine.py` — Model Escalation

```python
# If first model returns all-null or wrong document type → escalate
if empty or detected in ("other", "unknown"):
    model_used = settings.gemini_model_escalation  # gemini-3.1-pro-preview
    result = await _call_gemini(...)  # One more attempt with stronger model
```

**Escalation path:** `gemini-3.5-flash` → `gemini-3.1-pro-preview`. Only one escalation. If the pro model also fails, the extraction fails loudly.

### File: `validators.py` — Deterministic Post-Processing

**This is where Yunaki's thesis lives.** The VLM extracts, but the validators normalize and clean:

| Validator | Input | Output | Example |
|---|---|---|---|
| `check_date` | "03/15/1990" or "15-Mar-1990" | "1990-03-15" or null | Strict YYYY-MM-DD only |
| `check_sex` | "MALE", "male", "M" | "M" | Aliases map to canonical |
| `check_state` | "CA", "Calif.", "california" | "California" | Abbreviation → full name |
| `canonicalize_country` | "USA", "US", "United States" | "United States of America" | US variants only; non-US passes through |

**Rule:** Models never mutate. `data.model_copy(update={...})` returns a new instance.

### File: `coherence.py` — Cross-Document Consistency

```python
# Compare passport surname against G-28 beneficiary family_name
# Using rapidfuzz token_sort_ratio with threshold 85/100
score = fuzz.token_sort_ratio(passport_value.casefold(), g28_value.casefold())
if score < NAME_MATCH_THRESHOLD:
    warnings.append(FieldWarning(...))
```

**Key design decisions:**
- Fuzzy matching only, never hard block — these are warnings, not errors
- Null fields are skipped (null is a valid extraction, not a mismatch)
- Case-insensitive comparison
- Token sort ratio tolerates diacritics and word ordering

### File: `merge.py` — Passport Front/Back Merge

```python
# Front is authoritative; back fills nulls only
filled_from_back = [
    key for key, value in back.data.items()
    if merged_data.get(key) is None and value is not None
]
```

**Design:** Never override front data with back data. The front (photo page) is the source of truth. The back (MRZ/staples) only fills gaps.

---

## 3. POPULATION PLANE (DEEP DIVE)

### File: `field_map.py` — The Allow-List

**This is the ONLY source of selectors the population plane may touch.** 29 FieldSpecs total.

```python
@dataclass(frozen=True)
class FieldSpec:
    selector: str                 # CSS selector
    source: str                   # dotted path: "g28.attorney.city"
    action: Action = "fill"       # fill | select_label | select_value | check
    nth: int | None = None        # positional disambiguation (duplicate-id trap)
    check_when: bool | None = None  # for check: only check when source == this
```

**Three action types:**
1. **`fill`** — `locator.fill(text)` for text inputs
2. **`select_label`** — `locator.select_option(label="California")` for dropdowns where labels are full names but values are codes
3. **`select_value`** — `locator.select_option("CA")` for dropdowns where values match directly
4. **`check`** — `locator.check()` only when `value == check_when`. Never unchecks.

**Key traps documented in comments:**
- Part 3 First Name(s) AND Middle Name(s) both have `id="passport-given-names"` → middle name uses `nth=1`
- State dropdown: option values are 2-letter codes, labels full names → `select_label`
- Sex dropdown: values are M/F/X → `select_value`
- Discipline 1.c is TWO independent checkboxes (`#not-subject`, `#am-subject`), not radios
- Submit/sign/Part 4/Part 5 selectors are **structurally absent** — do not add them

### File: `fill.py` — The Write Engine

```python
async def populate_form(passport, g28, headed=None, *, target_url=None):
    # Budget model derived from settings.populate_timeout_ms (60s default)
    goto_ms = int(timeout_ms * 0.25)         # 15s for page load
    per_action_ms = max(1, (timeout_ms - goto_ms) // (2 * len(FIELD_MAP)))
    # 2 passes (write + verify), budget split evenly
    
    async with asyncio.timeout(outer_seconds):  # hard ceiling
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not run_headed)
            page = await browser.new_page()
            page.set_default_timeout(per_action_ms)
            await page.goto(url, timeout=goto_ms)
            writes = await _write_all(page, sources)      # Pass 1: write
            report = await verify_and_report(page, url, writes)  # Pass 2: verify
            report = await _attach_artifact(report, page, run_headed)  # Capture PDF
```

**Key design decisions:**
- Timeout budget derived from config, no magic numbers
- `asyncio.timeout` as hard outer ceiling — prevents runaway browser hangs
- Per-action timeout = budget / (2 × field count) — two passes, split evenly
- Write failures per-field → never abort the run
- Artifact capture (PDF/PNG) never fails the run

### File: `verify.py` — The Read-Back Engine

**After every write, every field is read back and compared:**

```python
status = "filled" if actual == write.expected else "mismatch"
```

**Four possible statuses:**
- **`filled`** — write happened, read-back matches intent
- **`skipped_null`** — source was null, no interaction, but audited anyway
- **`mismatch`** — read-back differs from intended state
- **`error`** — write or read-back raised an exception

**Population report:**
```python
class PopulationReport(BaseModel):
    target_url: str
    entries: list[PopulationEntry]
    filled: int = 0
    skipped_null: int = 0
    mismatches: int = 0
    errors: int = 0
    ok: bool = False  # True when mismatches == 0 and errors == 0
    artifact_id: str | None = None  # Content hash for download
    artifact_kind: Literal["pdf", "png"] | None = None
```

### File: `artifact.py` — Downloadable Filled Form

```python
# Headless → PDF via CDP printToPDF (crisp, searchable)
# Headed → PNG full-page screenshot (Chromium can't printToPDF headed)
async def capture_artifact(page: Page, headed: bool) -> tuple[bytes, ArtifactKind]:
    if headed:
        return await page.screenshot(full_page=True, type="png"), "png"
    return await page.pdf(print_background=True), "pdf"
```

**Storage:** Content-hash-named files under `{local_storage_dir}/artifacts/{sha256}.a28.pdf`. The ID is PII-safe to log and safe to put in URLs.

---

## 4. STORAGE PLANE

### File: `base.py` — Abstract Interface

```python
class DocumentStore(ABC):
    @abstractmethod
    async def save_document(self, content: bytes, doc_type: str, filename: str) -> str:
        """Persist original bytes; returns doc_id (content hash)."""
    
    @abstractmethod
    async def save_extraction(
        self, doc_id: str, envelope: ExtractionEnvelope, kind: ExtractionKind = "raw"
    ) -> None:
        """Persist extraction record keyed by (doc_id, doc_type, kind)."""
    
    @abstractmethod
    async def get_extraction(
        self, doc_id: str, doc_type: str, kind: ExtractionKind = "raw"
    ) -> ExtractionEnvelope | None:
        """Fetch previously saved extraction, if any."""
```

**Exactly three methods.** No more, no less.

**Key = (doc_id, doc_type, kind):** "raw" = straight from the model. "final" = post-merge/coherence, what the user saw. This preserves both the raw model output and the reviewed output.

### Factory Pattern

```python
def get_store() -> DocumentStore:
    if settings.supabase_enabled:
        return SupabaseStore(settings)
    return LocalStore(settings)
```

**Supabase when configured, local disk otherwise.** No code changes to switch backends.

---

## 5. OBSERVABILITY PLANE

### File: `observability.py` — Langfuse Tracing

**Three span types:**
1. **`request_trace`** — root span for one API request, grouped under session ID
2. **`stage_span`** — child span for pipeline stage (guardrails, render, validate, fill)
3. **`llm_generation`** — generation span around one Gemini call

**PII policy (stricter than the rest of the app):**
- Traces carry: content hashes, timings, token counts, page counts, field STATISTICS
- Traces carry: MASKED field previews (first character / date shape only)
- Traces NEVER carry: document bytes, rendered pages, raw extracted values, population expected/actual values

**Masking logic:**
```python
def mask_value(value: Any) -> str:
    if isinstance(value, bool):
        return "•"                    # Single glyph
    text = str(value)
    if _DATE_SHAPE.fullmatch(text):    # "1990-03-15" → "****-**-**"
        return "****-**-**"
    if len(text) <= 1:
        return "*"
    return text[0] + "*" * (len(text) - 1)  # "Smith" → "S****"
```

**Why strict masking?** Traces might be shared with Yunaki or debugging tools. Even hashes are safe; actual values are not.

---

## 6. PII / SECURITY MODEL

### Three-Tier PII Policy

| Tier | What | Where |
|---|---|---|
| **Never log** | Extracted values, document content, form values | Logs, traces, error messages |
| **Hash only** | Document identity | Logs, traces, storage keys |
| **Can log** | Field paths, error types, count statistics | Everywhere |

### Implementation Details

**1. `_safe_error_summary()` in `engine.py`:**
```python
def _safe_error_summary(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        # include_input=False → never leaks raw model output in error messages
        parts = [f"{'.'.join(str(loc) for loc in error['loc'])}:{error['type']}"
                 for error in exc.errors(include_input=False, include_url=False)]
    return type(exc).__name__
```

**2. Log lines in `engine.py`:**
```python
logger.info("extraction start doc_type=%s source_hash=%s size_bytes=%d", ...)
# No extracted values, no names, no numbers — just hash, doc type, size
```

**3. Telemetry endpoint validation:**
```python
class TelemetryEvent(BaseModel):
    name: str = Field(min_length=4, max_length=64, pattern=r"^ui\.[a-z0-9_.]+$")
    metadata: dict[str, TelemetryValue] = Field(default_factory=list)  # scalar-only
```

**4. Storage guard — never fail on persistence:**
```python
async def _save_guarded(save_coro, doc_label: str) -> bool:
    try:
        await save_coro
        return True
    except Exception:
        logger.exception("storage persistence failed for %s", doc_label)
        return False
# A working extraction is NEVER discarded over storage failure
```

---

## 7. SCHEMA DESIGN

### File: `schemas/common.py` — Shared Contracts

```python
DocType = Literal["passport", "g28"]  # DocType is frozen — add new forms deliberately

class ExtractionEnvelope(BaseModel):
    document_type_requested: DocType
    document_type_detected: DetectedType = "unknown"
    data: dict[str, Any] | None = None  # validated dump
    warnings: list[FieldWarning] = Field(default_factory=list)
    model_used: str | None = None
    source_hash: str | None = None  # SHA-256, PII-safe

class PopulationReport(BaseModel):
    target_url: str
    entries: list[PopulationEntry]
    filled: int = 0
    skipped_null: int = 0
    mismatches: int = 0
    errors: int = 0
    ok: bool  # True iff mismatches == 0 and errors == 0
    artifact_id: str | None = None
    artifact_kind: Literal["pdf", "png"] | None = None

class ApiResponse(BaseModel):
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
```

### File: `schemas/passport.py` — Passport Schema

```python
class PassportData(BaseModel):
    surname: str | None = Field(None, description="Family name exactly as printed, incl. diacritics")
    given_names: str | None = Field(None, description="First name(s) exactly as printed")
    middle_names: str | None = Field(None, description="Middle name(s) if the passport separates them")
    passport_number: str | None = None
    country_of_issue: str | None = Field(None, description="Full English country name")
    nationality: str | None = Field(None, description="Full English country/nationality name")
    date_of_birth: str | None = Field(None, description="YYYY-MM-DD")
    place_of_birth: str | None = None
    sex: str | None = Field(None, description="Single letter: M, F, or X")
    date_of_issue: str | None = Field(None, description="YYYY-MM-DD")
    date_of_expiration: str | None = Field(None, description="YYYY-MM-DD")
```

**Every field Optional with default None.** A missing value is a valid result, never a parsing failure.

### File: `schemas/g28.py` — G-28 Schema

```python
class AttorneyInfo(BaseModel):
    online_account_number: str | None = None
    family_name: str | None = None
    given_name: str | None = None
    middle_name: str | None = None
    street_number_and_name: str | None = None
    apt_ste_flr: Literal["apt", "ste", "flr"] | None = Field(...)
    apt_ste_flr_number: str | None = None
    city: str | None = None
    state: str | None = Field(None, description="...address block only...")
    zip_code: str | None = None
    country: str | None = Field(None, description="Full English country name")
    daytime_phone: str | None = Field(None, description="Item 4 ONLY. Never fax.")
    mobile_phone: str | None = Field(None, description="Item 5 ONLY. Never fax.")

class EligibilityInfo(BaseModel):
    is_attorney: bool | None = Field(None, description="Box 1.a checked")
    licensing_authority: str | None = None
    bar_number: str | None = None
    subject_to_discipline: bool | None = Field(None, description="1.c — True if 'am' subject...")
    law_firm: str | None = None
    is_accredited_representative: bool | None = None
    recognized_organization: str | None = None
    accreditation_date: str | None = Field(None, description="YYYY-MM-DD")
    is_associated: bool | None = None
    associated_with_name: str | None = None
    is_law_student: bool | None = None
    law_student_name: str | None = None

class BeneficiaryInfo(BaseModel):
    family_name: str | None = None
    given_name: str | None = None
    middle_name: str | None = None

class G28Data(BaseModel):
    attorney: AttorneyInfo = Field(default_factory=AttorneyInfo)
    eligibility: EligibilityInfo = Field(default_factory=EligibilityInfo)
    beneficiary: BeneficiaryInfo = Field(default_factory=BeneficiaryInfo)
```

**Key design:** Nested models mirror form sections. `default_factory` ensures nested models are never None — always an empty instance.

---

## 8. TESTING & EVALUATION

### File: `test_extraction_golden.py` — Golden Tests

**Strategy:** Cache extraction results keyed by `(file_hash, model, prompt_hash)`. Reruns are free unless `YUNAKI_REFRESH_EXTRACTION_CACHE=1`.

```python
CACHE_DIR = Path(__file__).parent / ".extraction_cache"

def _cache_path(file_bytes, doc_type):
    file_hash = hashlib.sha256(file_bytes).hexdigest()[:16]
    prompt_hash = hashlib.sha256(prompts.extraction_prompt(doc_type).encode()).hexdigest()[:8]
    model_slug = settings.gemini_model.replace("/", "_")
    return CACHE_DIR / f"{doc_type}-{file_hash}-{model_slug}-{prompt_hash}.json"
```

**Test categories:**
1. **Exact value tests** — `test_g28_field` paramatrized over 20 expected (path, value) pairs
2. **Null contract tests** — N/A fields must be null, not guessed
3. **Document type detection** — `test_g28_detected_as_g28`
4. **Source hash integrity** — output hash matches input hash
5. **Model recording** — `model_used` is always set
6. **Cross-contamination tests** — fax number must not leak into any field
7. **Date format contract** — all dates must parse as YYYY-MM-DD
8. **Sex normalization** — must be M, F, X, or null

**Fixture-based:** Tests skip when fixtures are absent (no hard dependency on API key for offline testing).

### Eval Harness Evolution

| Run | Fields Correct | What Changed |
|---|---|---|
| 1 | 98.4% | Initial prompt + schema |
| 2 | 99.8% | Added normalization rules in prompt |
| 3 | 100% | Added field-specific descriptions + examples |

This proves convergence through prompt engineering, not model changes.

---

## 9. FRONTEND FLOW

### Component Structure

```
page.tsx (entry)
  └── AutofillFlow (state machine)
       ├── UploadSlot (file upload per slot)
       ├── DocumentStep (upload UI)
       ├── PassportReviewStep (review passport extraction)
       ├── G28ReviewStep (review G-28 extraction)
       ├── PopulateStep (run population, show report)
       └── ReportStage (download artifact, show mismatches)
```

### Key Frontend Concepts

1. **Review table** — every extracted field is editable before population
2. **Slot-level errors** — one bad file never discards another's result (parallel extraction)
3. **Warnings surface** — coherence warnings (name mismatch) appear in the review table
4. **Artifact download** — filled form PDF/PNG available after population
5. **Telemetry** — UI events (step transitions, extraction outcomes) sent to `/api/telemetry`

---

## 10. DESIGN DECISIONS & RATIONALE

| Decision | Alternatives Considered | Why This Choice | Tradeoff |
|---|---|---|---|
| **Gemini over GPT-4o/Claude** | GPT-4o, Claude Sonnet | Deterministic JSON at temp 0, Pydantic-enforced schema, lower cost | Locked to Google ecosystem |
| **Temperature 0** | 0.0-0.3 range | Forms are deterministic; hallucination = denial | Less creative flexibility (not needed here) |
| **Pydantic for output schema** | JSON schema, manual parsing | Type-safe, validation built-in, retry on failure | Requires Pydantic-compatible model |
| **Normalization at extraction time** | Normalize at fill time | Prevents "03/15/1990" vs "1990-03-15" false mismatches | Extra step in extraction pipeline |
| **Playwright over Puppeteer/Selenium** | Puppeteer, Selenium | Python-native, debugable, surgical selectors, great async API | Slightly heavier than raw WebDriver |
| **Local-first storage** | Cloud-only | Demo works without backend; Supabase for production | Local disk not suitable for multi-instance deploy |
| **3-method storage interface** | Direct Supabase calls | Swap backends without changing business logic | Extra abstraction layer |
| **Model escalation (flash → pro)** | Single model, prompt tuning | Cheaper model first, stronger model only when needed | Two API calls on hard cases |
| **Content-hash IDs** | UUIDs, auto-increment | PII-safe to log, safe in URLs, deterministic | Longer strings |
| **Verify read-back after every write** | Trust the write | Catches DOM state mismatches (JS, sticky headers) | Extra pass doubles browser time |
| **Budget-based timeout model** | Fixed timeouts | Adapts to field count; no magic numbers | Complexity in calculation |
| **guardrail rejections = ValueError** | HTTP error codes | User-actionable (re-upload), not server failure | Requires client to handle both error shapes |

---

## 11. EDGE CASES HANDLED

### Upload Edge Cases

| Case | Handling |
|---|---|
| File exceeds 10 MB | `_read_capped` returns None → `{"error": "File exceeds limit"}` |
| File is corrupted/unrecognized | `sniff_format` raises ValueError → user re-uploads |
| PDF is password-protected | `fitz.open` catches → ValueError with re-scan message |
| PDF has 0 pages | ValueError |
| PDF exceeds 10 pages | ValueError |
| Image too low-res (< 500px short side) | `assert_page_quality` rejects → re-scan |
| Image too blurry (Laplacian variance < 40) | `assert_page_quality` rejects → re-scan |
| Wrong document in slot | `document_type_detected != doc_type` → withhold extraction, show warning |
| Storage fails | `_save_guarded` catches → extraction shown, warning added |

### Extraction Edge Cases

| Case | Handling |
|---|---|
| VLM returns invalid JSON | Retry once, then RuntimeError with hash-only message |
| All fields null | Escalate to stronger model |
| Wrong document type detected | Escalate to stronger model |
| Fax number on G-28 (unmapped field) | Not in FIELD_MAP → never extracted; test asserts absence |
| N/A or blank fields | Normalized to null, not guessed |
| Passport back without front | Accepted but merge warns; front-only extraction works fine |

### Population Edge Cases

| Case | Handling |
|---|---|
| Source value is null | `skipped_null` — no interaction, audited via read-back |
| Source path doesn't exist | `resolve_source` raises KeyError → caught per-field, status "error" |
| Wrong action type for value | `_checkbox_intent` / `_require_str` raises → caught, status "error" |
| Checkbox should be unchecked | No interaction, but verified read-back must show unchecked |
| Duplicate-id trap (given-names) | `nth=0` and `nth=1` resolve positionally |
| Select option not found | Playwright raises → caught, status "error" |
| Artifact capture fails | Report returned without artifact_id; never fails run |
| Browser times out | `asyncio.timeout` outer ceiling → TimeoutError, caught by API handler |

### Coherence Edge Cases

| Case | Handling |
|---|---|
| Null field on one side | Skipped (null is valid, not a mismatch) |
| Different name order | `token_sort_ratio` handles word reordering |
| Diacritics | Casefold comparison tolerates accents |
| Score exactly 85 | Not flagged (threshold is `< 85`, not `<=`) |

---

## 12. WHAT I'D CHANGE WITH HINDSIGHT

### High-Value Changes

1. **Add a retry for transient VLM failures.** Currently only 2 attempts total (1 retry). For production, exponential backoff with 3-5 retries on 5xx/timeout.

2. **Batch Gemini calls.** Right now each document is extracted independently. For multi-document uploads, parallelize the Gemini calls with `asyncio.gather()`.

3. **Add a confidence score per field.** The VLM doesn't return one, but post-processing heuristics (was the field null after validation, was it fuzzy-matched, was it escalated) can derive a rough confidence.

4. **Make the field map a YAML/JSON config file.** Right now it's Python code. For production, a config file means adding new forms is a deploy-free config change.

5. **Add rate limiting on the population endpoint.** Right now there's none. Playwright is resource-heavy; concurrent requests could exhaust the server.

6. **Add request idempotency keys.** If the client retries a failed extraction, the server should detect the duplicate and return the cached result instead of hitting Gemini again.

7. **Separate the extraction temperature per document type.** Currently one global `extraction_temperature`. Passport is highly structured → lower temp. G-28 has more narrative → slightly higher temp might help.

### Low-Priority / Nice-to-Have

8. **Add a health check for Gemini API key validity** at startup, not just at first request.
9. **Rotate Supabase credentials** without downtime.
10. **Add a "dry run" mode** for population that shows what would be filled without actually filling.
11. **Support multi-page form population** (fill one page, navigate to next, fill again). Currently single page only.

---

## 13. HOW TO EXTEND THIS SYSTEM

### Adding a New Document Type (e.g., I-864)

**Follow this checklist:**

1. **Add DocType literal:** `DocType = Literal["passport", "g28", "i864"]` in `schemas/common.py`

2. **Create schema:** `backend/app/schemas/i864.py`
   ```python
   class I864Data(BaseModel):
       sponsor_name: str | None = None
       household_size: int | None = None
       annual_income: str | None = Field(None, description="USD, e.g. '45000'")
       # ... all fields Optional with null default
   ```

3. **Add data model mapping in `engine.py`:**
   ```python
   _DATA_MODEL: dict[DocType, type[BaseModel]] = {
       "passport": PassportData,
       "g28": G28Data,
       "i864": I864Data,
   }
   ```

4. **Create validator:** `backend/app/extraction/validators_i864.py`
   - Same pattern: normalization, null handling, warnings
   - Income validation, poverty guideline checks, household size algorithm

5. **Add prompt:** `_DOC_LABEL["i864"] = "Form I-864 (Affidavit of Support)"`

6. **Create field map for population:** `backend/app/population/field_map_i864.py`
   - Same FieldSpec pattern, action types, selector allow-list

7. **Add API endpoint or extend `/api/extract`:**
   - Currently hardcoded for passport + g28. Generalize to accept `doc_type` parameter.

8. **Add golden tests:** `test_i864_field` with expected values from sample form.

### Generalizing from 2 Forms → 200 Forms

**Current architecture:** 2 document types, hardcoded in API routes, hardcoded field maps, hardcoded schemas.

**To generalize:**

| Current | Generalized |
|---|---|
| `DocType = Literal["passport", "g28"]` | `DocType = Literal["passport", "g28", "i864", "i130", ...]` |
| Hardcoded `/api/extract` slots | `{doc_type: UploadFile}` dynamic slots |
| Per-doc validators module | Registry: `VALIDATORS: dict[DocType, callable]` |
| Per-doc field_map.py | Config-driven: `field_maps/{doc_type}.yaml` |
| Per-doc schema module | Auto-generated from YAML schema definitions |
| Per-doc prompt | Template: `prompts/{doc_type}.txt` |

**The engine doesn't change.** `extract_document()` is already generic — it takes `doc_type` as a parameter. The generalization is plumbing, not architecture.

### Adding Cross-Form Consistency Checks

**Current:** Only passport ↔ G-28 name check (coherence.py).

**To add I-130 ↔ I-485 ↔ I-864 consistency:**

```python
# New file: backend/app/extraction/cross_form.py

class CrossFormChecker:
    def __init__(self, forms: dict[str, BaseModel]):
        self.forms = forms
    
    def check_consistency(self) -> list[FieldWarning]:
        # For each CRITICAL field across all form pairs:
        #   normalize both values
        #   if different: flag with severity
        # Return aggregated warnings
```

**FIELD_MAP for consistency:**
```python
CONSISTENCY_FIELDS = {
    "date_of_birth": {"forms": ["i130", "i485", "i864"], "severity": "CRITICAL"},
    "a_number": {"forms": ["i485", "i864"], "severity": "CRITICAL"},
    "country_of_birth": {"forms": ["i130", "i485"], "severity": "WARNING"},
    "address": {"forms": ["i130", "i485", "i864"], "severity": "WARNING"},
}
```

---

## 14. LIKELY INTERVIEW QUESTIONS & ANSWERS

### Q1: "Walk me through your architecture."

> "The system has four planes: extraction, population, storage, and observability.
>
> Extraction takes uploaded files, renders them to images, runs a quality gate (resolution + blur), sends them to Gemini with a structured JSON schema at temperature 0, then post-processes the output through deterministic validators that normalize dates, states, countries, and sex fields. If the first model returns null-heavy or wrong-document results, it escalates to a stronger model.
>
> Population takes the validated extraction and fills a target form using Playwright. Every field in the FIELD_MAP allow-list is written, then read back and verified. The read-back diff is the population report.
>
> Storage is abstracted behind a 3-method interface — Supabase in production, local disk for demo. Every blob is keyed by content hash, so files are PII-safe to reference.
>
> Observability uses Langfuse tracing with strict PII masking — content hashes and field statistics, never actual values."

### Q2: "Why temperature 0?"

> "Because this is a legal form system. Hallucination isn't a minor bug — it's a wrong date, a wrong number, a wrong name on a government form that costs the applicant months of delay and hundreds of dollars in fees. Temperature 0 with Pydantic schema enforcement gives us deterministic output. The only randomness we want is in the retry logic, not in the extracted values."

### Q3: "How do you handle VLM output that doesn't match the schema?"

> "Two layers. First, Gemini's `response_schema` enforces the Pydantic model at the API level — it won't return JSON that doesn't match. Second, if that fails, we have a retry loop with explicit `model_validate_json` and structured error logging. If both attempts fail, we raise a RuntimeError with the source hash — the error message never contains extracted values. And we log field-level validation errors with `include_input=False` so the ValidationError's `input_value` fragments don't leak into logs."

### Q4: "Why normalize at extraction time instead of fill time?"

> "Two reasons. First, it prevents false mismatches — if the passport has '03/15/1990' and the form expects '1990-03-15', normalizing once at extraction means we never compare different formats. Second, the normalized value is what the user sees in the review table, so they confirm the canonical form before we ever touch the target form. If we normalized at fill time, a bug in the normalizer would silently populate the wrong value."

### Q5: "How does the read-back verification work?"

> "After every field is written, we read it back from the live DOM and diff against the intended state. Four statuses: filled, skipped_null, mismatch, error. The `ok` flag is True only when there are zero mismatches and zero errors. This catches DOM state mismatches — sticky headers overriding inputs, JS resetting fields, checkboxes that didn't stick. It's the same principle as a two-phase commit: write, verify, report."

### Q6: "What's your PII approach?"

> "Three tiers. Never log: extracted values, document content, form field values. Hash only: document identity (SHA-256 of upload bytes), safe to log and put in URLs. Can log: field paths like `attorney.state`, error types like `ValidationError`, count statistics. The masking function in observability.py strips all but the first character of any value that might appear in traces. And the telemetry endpoint only accepts scalar metadata — no free-form text that could accidentally capture PII."

### Q7: "Why Pydantic models instead of plain dicts?"

> "Pydantic gives us three things for free: type validation at the boundary (invalid JSON → loud failure, not silent corruption), `model_dump()` for serialization, and `model_copy(update=...)` for immutable transformations in validators. The extraction schemas are the contract between the VLM and the rest of the system — Pydantic enforces that contract at runtime."

### Q8: "How would you scale this to 100 concurrent users?"

> "The extraction plane scales horizontally — it's stateless between requests. The main bottleneck is the Gemini API rate limit, so I'd add a request queue with backpressure. The population plane is heavier because each request launches a Chromium instance — I'd add a semaphore to cap concurrent browsers and a connection pool. Storage is already abstracted, so scaling Supabase is independent. The eval cache already prevents redundant API calls during development."

### Q9: "What happens if the Gemini API goes down?"

> "We have two fallback layers. First, the retry loop handles transient failures. Second, the `/api/health` endpoint reports `gemini_key_present` so the frontend can warn users before they upload. If the API is completely down, extraction raises a RuntimeError that surfaces as a user-facing error — not a 500. For production, I'd add a circuit breaker pattern and a degraded mode that lets users manually fill the form."

### Q10: "What's the biggest weakness in your current system?"

> "Honest answer: the eval harness measures goldens, not edge cases. I have tests for known inputs, but I don't have adversarial tests — what happens with a photocopy instead of a scan, what happens with a torn document, what happens with 12-language passports. The second weakness is that population is single-page only — the G-28 is one page, but the I-864 is 10+ pages. I'd need a multi-step population flow with per-page FIELD_MAPs and navigation."

### Q11: "Why Playwright over Selenium or Puppeteer?"

> "Three reasons. First, Python-native async API — no process bridge like Puppeteer's node subprocess. Second, the locator API is more robust than Selenium's CSS selectors — Playwright auto-waits for elements, handles shadow DOM, and has built-in retry logic. Third, the `page.pdf()` with `print_background=True` gives us a real PDF artifact, not a screenshot. Selenium can't do that."

### Q12: "Tell me about a time you made a wrong technical decision."

> "The duplicate-id trap in the G-28 form. I initially tried to select the middle name input by its label text, then by a sibling selector, before realizing both First Name(s) and Middle Name(s) inputs share the same `id` and `name` attribute. The solution was positional `nth()` — simple once I identified the root cause, but I spent an hour on fragile workarounds first. The lesson: when selectors fail, inspect the DOM tree, don't guess at CSS combinators."

### Q13: "How do you know your system works?"

> "Three layers. First, unit tests for validators, coherence, and storage. Second, golden extraction tests that run the full pipeline against known fixtures and assert exact field values — cached so reruns are instant. Third, the eval harness: three runs showing 98.4% → 99.8% → 100%, proving that prompt engineering converges. I also have integration tests for population against a static HTML snapshot, so the Playwright pipeline runs offline."

### Q14: "What would you do differently if you were building this for production?"

> "Four things. One, add a config-driven field map so new forms don't require code changes. Two, add rate limiting and a request queue for the population endpoint since Chromium is resource-heavy. Three, add request idempotency keys so retried uploads don't hit Gemini twice. Four, add per-field confidence scores derived from the VLM output heuristics, not just pass/fail. The architecture is sound — it's the operational layers that need hardening."

---

*End of system mastery document. This covers every component in your actual codebase. Study the files referenced here — especially engine.py, field_map.py, validators.py, and verify.py. These are the files the interviewer will dive into.*
