# How I'd Explain This in an Interview
## The Human Version

---

## THE PROBLEM WE WERE SOLVING

Immigration attorneys spend hours copying data from passports and G-28 forms into government PDFs. One wrong digit, one wrong date format, and USCIS rejects the filing. The take-home asked us to build an autofill system — upload documents, extract structured data, fill a target form, and verify everything landed correctly.

I built this as "Yunaki" — my thesis being that legal automation needs deterministic guardrails around AI, not just raw LLM calls. The system extracts data from documents, normalizes it to canonical forms, fills a target USCIS form using Playwright, and reads every field back to confirm it stuck.

---

## REQUIREMENTS — What the System Does

### Upload Requirements

- Accept passport images (JPEG/PNG) and multi-page PDFs
- Reject files over 10 MB, password-protected PDFs, and PDFs longer than 10 pages
- Check image quality before sending to the AI — reject blurry scans and low-resolution photos
- Detect the actual document type — if someone uploads a driver's license instead of a passport, we catch it

### Extraction Requirements

- Extract structured data from passport images and G-28 forms
- Every field is optional — missing data is null, not a guess
- Normalize dates to YYYY-MM-DD, countries to full English names, states to full names
- If the first model returns nothing useful, escalate to a stronger model automatically
- Detect cross-document mismatches — if the passport name differs from the G-28 name, flag it

### Population Requirements

- Fill a target form (currently the A-28 submission form) using Playwright
- Only touch fields in an explicit allow-list — no arbitrary DOM manipulation
- Handle different field types: text inputs, dropdowns, checkboxes
- Read every field back after writing to verify it landed correctly
- Capture a downloadable artifact — PDF in headless mode, PNG if watching it run live

### Reliability Requirements

- Write failures per field are never fatal — one broken field doesn't abort the whole run
- Storage failures never discard an extraction — show the result anyway, warn the user
- Never log extracted values — hashes only, for privacy
- The system must tell the user exactly what went wrong and what to do about it

---

## CORE ENTITIES — The Main Concepts

**Document** — the raw bytes a user uploads. Identified by its content hash (SHA-256). We never use filenames as identity because two different files can have the same name.

**ExtractionEnvelope** — the wrapper around every extraction result. It contains: what document type we asked for, what the AI actually detected, the extracted data, any warnings, which model was used, and the source hash. This is the contract between the AI layer and everything else.

**FieldSpec** — a single instruction for the population engine. It says: "find this CSS selector, pull data from this dotted path in the extracted data, and use this action (fill, select, or check)." There are about 30 of these for the A-28 form.

**PopulationEntry** — the result of writing one field and reading it back. It has four possible states: filled correctly, skipped because the source was null, mismatch between what we wrote and what's in the DOM, or error if something broke.

**PopulationReport** — the aggregate result of a full form population. Counts of filled/skipped/mismatch/error entries, plus a single `ok` boolean that's true only when there are zero mismatches and zero errors.

**FieldWarning** — a non-fatal issue from extraction or coherence checking. Examples: "name on passport differs from name on G-28" or "back-side image doesn't look like a passport."

---

## API ENDPOINTS — What You Can Call

### POST /api/extract

Upload one or more documents, get structured data back.

**Input:** multipart form data — passport image plus optional G-28 PDF.

**What happens:**
1. Read the file, check size limit
2. Detect format by magic bytes (not by filename extension — that's a security issue)
3. Render PDF pages to images, or load the image directly
4. Check resolution and blur before sending to the AI
5. Call Gemini with a structured JSON schema at temperature 0
6. If the first model returns null-heavy results, escalate to a stronger model
7. Run deterministic validators — normalize dates, states, countries
8. Cross-check passport against G-28 for name consistency
9. Return the ExtractionEnvelope with data and warnings

**Output:** JSON with success flag, extracted data per document, warnings, and source hashes.

### POST /api/populate

Fill the target form from validated extraction data.

**Input:** JSON body with the extracted passport and G-28 data.

**What happens:**
1. Launch a headless Chromium browser via Playwright
2. Navigate to the target form URL with a timeout budget
3. For each field in the FIELD_MAP allow-list: resolve the source path, write the value, record the intent
4. After all writes complete, read every field back from the live DOM
5. Diff read-back against intent — populate the report
6. Capture a PDF artifact of the filled form
7. Return the PopulationReport with per-field status

**Output:** JSON with filled/skipped/mismatch/error counts, per-field entries, artifact download ID.

### GET /api/health

Simple health check. Reports whether the Gemini API key is configured and storage is working. No extraction occurs.

---

## DATA FLOW — What Actually Happens

### Upload → Extract → Review → Populate

**Step 1: Upload**
User drops a passport image and a G-28 PDF into the frontend. The frontend sends them to `/api/extract`. The backend reads each file into memory, checks the size, and validates the format.

**Step 2: Render**
A PDF gets split into page images at 220 DPI. A JPEG or PNG loads directly. Each page goes through a quality gate: is the short side at least 500 pixels? Is the Laplacian variance above 40 (not blurry)? A blurry scan never reaches the AI — we reject it upfront and tell the user to re-scan.

**Step 3: Extract**
Each page image becomes a PNG byte array. We send it to Gemini with a prompt that says "extract structured data from this passport image" and a Pydantic schema that defines every field. Temperature is 0 — we want deterministic output, not creative guessing. Gemini returns structured JSON that matches our schema.

**Step 4: Validate**
The raw extraction goes through validators. Dates that arrived as "03/15/1990" become "1990-03-15". "CA" becomes "California". "USA" becomes "United States of America". "MALE" becomes "M". Fields that were blank or "N/A" stay null — the VLM is instructed never to guess.

**Step 5: Coherence**
If both a passport and a G-28 were uploaded, we compare the surname and given name. Not a hard block, but a warning — people get married, typos happen. We use fuzzy matching (token sort ratio) with an 85% threshold so minor differences don't trigger false alarms.

**Step 6: Frontend Review**
The extracted data comes back to the frontend as an editable review table. The user can change any value before we fill the form. This is important — the AI might extract correctly, but the user knows best.

**Step 7: Populate**
When the user confirms, the frontend calls `/api/populate` with the (possibly edited) data. Playwright opens the A-28 form, and for each field in the FIELD_MAP, it resolves the dotted source path (like `passport.surname` or `g28.attorney.city`), applies the value to the DOM, and records what it intended to write.

**Step 8: Verify**
After all fields are written, Playwright reads every field back from the DOM. If what we read matches what we wrote, it's `filled`. If it differs, it's a `mismatch`. If the source was null, it's `skipped_null`. If something broke, it's `error`. The `ok` flag is true only when there are zero mismatches and zero errors.

**Step 9: Artifact**
We capture a snapshot of the filled form — a PDF in headless mode, a PNG if we're running with a visible browser. The user can download it. The file is stored on disk under a content-hash name, so the ID is safe to log and safe to put in a URL.

---

## HIGH-LEVEL DESIGN — How I'd Draw This on a Whiteboard

Three layers, two AI boundaries:

```
┌─────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js)                    │
│   Upload → Review table → Confirm → Download artifact     │
└──────────────────────────┬──────────────────────────────┘
                           │ /api/extract, /api/populate
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   FASTAPI BACKEND                        │
│                                                          │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐ │
│  │ Extraction   │    │  Population   │    │  Storage    │ │
│  │  Plane       │    │   Plane       │    │   Plane     │ │
│  │              │    │               │    │             │ │
│  │ • Quality    │    │ • Field map   │    │ • Abstract  │ │
│  │   gate       │    │ • Fill engine │    │   interface │ │
│  │ • VLM call   │    │ • Read-back   │    │ • Local or  │ │
│  │ • Normalize  │    │   verify      │    │   Supabase  │ │
│  │ • Validate   │    │ • Artifact    │    │ • Content   │ │
│  │ • Coherence  │    │   capture     │    │   hash IDs  │ │
│  └──────┬───────┘    └──────┬───────┘    └──────┬──────┘ │
│         │                   │                    │        │
│         ▼                   ▼                    ▼        │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              OBSERVABILITY (Langfuse)                │ │
│  │   Pipeline traces with PII masking — never raw data  │ │
│  └─────────────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
    ┌──────────────────┐      ┌──────────────────┐
    │  GEMINI (VLM)    │      │  PLAYWRIGHT      │
    │  Structured JSON  │      │  Browser control  │
    │  extraction       │      │  form fill        │
    └──────────────────┘      └──────────────────┘
```

**The key insight:** There are two AI boundaries — extraction (image to data) and population (data to form). Everything between them is deterministic. The AI is powerful but bounded; the guardrails are what make it production-ready.

---

## DEEP DIVES — Where the Interesting Decisions Live

### 1. Why Temperature 0?

This sounds trivial, but it's the most important architectural choice. Legal forms are not creative writing. If the VLM hallucinates a date or a number, that's not a minor bug — it's a filing that gets rejected, costing the applicant months and hundreds of dollars. Temperature 0 with Pydantic schema enforcement gives us deterministic output. The only "randomness" is in the retry logic when something fails.

I chose Gemini because it supports structured JSON output with a Pydantic schema at the API level. The model literally cannot return JSON that doesn't match our schema. That's a much stronger guarantee than asking for JSON in the prompt and parsing it.

### 2. Normalization at Extraction Time

I normalize dates, countries, and states the moment they come out of the AI — not when I'm filling the form. This is a subtle but critical design choice.

If I left dates as-is, the passport might have "03/15/1990" and the form field might expect "1990-03-15". Comparing those two strings would flag a false mismatch. By normalizing once at extraction time, the user sees the canonical form in the review table, confirms it, and we never compare different formats downstream.

Also, the normalized value is what we write to the form. So if there's a bug in the normalizer, the user catches it in the review table before we ever touch the target form. That's the safety net.

### 3. The Read-Back Verification

After Playwright writes every field, it reads every field back from the live DOM and compares against the intended value. This sounds redundant — we just wrote it, why read it back? — but browsers are messy.

JavaScript can reset fields. Sticky headers can overlay inputs. A dropdown might not have registered the selection. CSS transitions might visually show one value while the DOM holds another. Read-back catches all of that.

The report has four states: `filled` (wrote correctly, read back matches), `skipped_null` (no source data to write, but we checked the control anyway), `mismatch` (wrote something, DOM says something else), and `error` (something broke mid-operation).

The `ok` flag is true only when mismatches == 0 and errors == 0. That's the user's signal: "safe to download and submit."

### 4. The FIELD_MAP Allow-List

The population plane can only touch selectors explicitly listed in FIELD_MAP. This is the allow-list pattern — the opposite of "find all inputs and fill them." 

Why? Because government forms have traps. The G-28 form has two inputs that share the same `id` attribute — both First Name(s) and Middle Name(s) have `id="passport-given-names"`. A naive selector would fill the wrong field. My FIELD_MAP resolves this with positional `nth()` — first match for given names, second match for middle names.

The FIELD_MAP also documents traps in comments: "state dropdown values are 2-letter codes but labels are full names, so we select by label not value." "Sex dropdown values are M/F/X, so we select by value." "Discipline checkbox is two independent checkboxes, not radio buttons." "Submit and signature controls are structurally absent."

These aren't in a wiki — they're in the code, right next to the selectors that care about them.

### 5. Model Escalation

The system tries the cheaper, faster model first (`gemini-3.5-flash`). If it returns all-null results or detects the wrong document type, it escalates to the stronger model (`gemini-3.1-pro-preview`) for one more attempt.

This is a cost optimization. Most documents extract fine with flash. Only the hard cases — weird fonts, unusual layouts, torn scans — need the pro model. On aggregate, maybe 10-15% of documents need escalation. That's a significant cost saving at scale.

The escalation is automatic. The user never sees it happen. They just get a result.

### 6. Front/Back Passport Merge

Passports have data on both sides. The front (photo page) is authoritative — it has the name, dates, passport number. The back (MRZ — the machine-readable zone at the bottom) sometimes has additional data, but often it's just staples or notes.

My merge logic: front wins. The back only fills fields that the front left null. Never override. This prevents a noisy or misread back side from corrupting a correct front-side extraction.

If the back side doesn't look like a passport at all — say the user uploaded the wrong image — we detect it, add a warning, and ignore the back entirely.

### 7. PII — Privacy Is Not Optional

This is a legal tech product. Extracted data is some of the most sensitive information a person has: passport numbers, alien registration numbers, addresses, dates of birth.

I built PII protection in three layers:

**Never log:** Extracted values never appear in log lines. The engine logs only the doc type, source hash, and file size. No names, no numbers, no dates.

**Hash only:** The document identity is a SHA-256 of the raw bytes. This is safe to log, safe to put in URLs, safe to reference from traces. It can't be reversed to recover the original document.

**Masked traces:** The observability layer strips all but the first character from any value that might appear in Langfuse traces. Dates render as `****-**-**`. Names render as `S****`. The masking function is strict — it's easier to over-mask and lose some debugging info than to accidentally leak PII.

The telemetry endpoint only accepts scalar metadata — no free-form text that could capture extracted values.

---

## WHAT I'D DO DIFFERENTLY

I'm honest about what I'd change:

1. **The field map should be a config file, not Python code.** Right now adding a new form means writing code. In production, a YAML file means a config change, not a deploy.

2. **Population needs rate limiting.** Each request launches a Chromium browser. At 100 concurrent users, that's 100 browser instances. I'd add a semaphore cap and a request queue.

3. **No request idempotency.** If the client retries a failed extraction, we hit Gemini again. I'd add idempotency keys so retries return cached results.

4. **The eval harness tests known inputs, not edge cases.** I have golden tests for exact field values, but I don't have adversarial tests — torn documents, photocopies, 12-language passports, handwritten forms.

5. **Population is single-page only.** The G-28 is one page, but the I-864 is ten pages. I'd need a multi-step population flow with per-page field maps and navigation.

---

## WHY THIS ARCHITECTURE

The core thesis — and the reason I built it this way — is that AI in legal automation needs guardrails, not just raw model output. The LLM is powerful, but it's not reliable enough to sign a government form.

So the architecture is: AI for the hard part (reading a messy scanned image and extracting structured data), deterministic code for everything else (normalizing, validating, comparing, writing, verifying). The AI never touches the target form directly. It extracts, the validators clean, the population engine writes, and the read-back verifies.

That's what makes it safe for production: not that the AI is perfect, but that the system catches its mistakes before they reach the user.

---

*This is the human version. Study these narratives and you'll be able to tell the story of what you built naturally, without memorizing specs.*
