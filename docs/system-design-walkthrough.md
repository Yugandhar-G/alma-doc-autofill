# System Design Walkthrough. YUNAKI as a GenAI Interview Answer

This doc has two jobs, in order:

- **Part 0** teaches you your own system in plain English. What every component
  actually is, with the real code from this repo. Read it until nothing in it
  surprises you.
- **Parts 1 to 5** are the interview delivery: the same system presented in the
  5-step arc (frame → high-level → deep dive → trade-offs → conclusion), with
  time boxes and scripts.

The hook that makes this real: a recruiter-shared interview question from
igotanoffer's GenAI guide reads *"Design a system to process 10k user uploads per
month (bank payslips, IDs, references). How would you extract data, detect
inconsistencies, reject invalid files, and handle LLM provider downtime?"*
That is this system. You built the answer. This doc teaches you to present it.

Companion docs: [system-mastery.md](system-mastery.md) (full reference, decision
table §10, scripted Q&A §14) · [hdd-interview-flow.md](hdd-interview-flow.md) ·
[human-interview-narrative.md](human-interview-narrative.md) ·
[tech-research.md](tech-research.md) (vendor comparisons, cost model).

---

# Part 0. Understand your own system first

## 0.1 The story of one document, no jargon

A paralegal named Maria has a client's passport photo and a signed G-28 form
(the government form that says "this lawyer represents this person"). She needs
that information typed into a web form. Here is what happens when she uses your
system instead of typing:

1. Maria drags the passport photo into the browser. Before anything is sent,
   the page itself checks: is this actually an image or PDF, and is it under
   10 MB? If not, she's told immediately.
2. The file travels to your server. The server checks the same two things
   again, because a server never trusts what a browser claims.
3. If it's a PDF, the server turns each page into a picture (an AI vision model
   reads pictures, not PDFs). Maximum 10 pages.
4. Each picture is checked: is it big enough to read? Is it too blurry? If it
   fails, Maria gets "this image is too blurry, retake the photo" and the AI is
   never called, so no money is spent on a hopeless image.
5. The picture goes to Google's Gemini model with strict instructions: "read
   this passport and fill in exactly this list of fields. If you cannot read a
   value, leave it empty. Never guess."
6. The model's answers pass through cleanup rules: dates become `1990-03-15`
   format, "CA" becomes "California", and anything invalid is blanked out and
   flagged with a warning instead of silently kept.
7. Everything is saved (twice: the model's raw answer and the cleaned-up
   version Maria will see) and sent back to her browser.
8. Maria now sees a review table: every extracted value in an editable box,
   with warnings next to anything suspicious. She fixes a typo, fills in a
   blank the model couldn't read. Nothing she does here touches the server.
9. She clicks Populate. Her reviewed values go to the server, which launches a
   real Chrome browser (invisible, no window) and drives it like a robot:
   click this box, type this value, pick this dropdown option. It only knows
   how to touch the 40 form fields on its approved list. The submit button is
   not on the list, so the robot cannot press it.
10. After typing everything, the robot goes back and reads every field off the
    page: "did the value I typed actually land?" Any difference is recorded.
11. Maria gets a report: green "Verified" if every field checked out, red
    "Do not trust this fill" if anything didn't, plus a PDF snapshot of the
    filled form she can download as proof.
12. She reviews the form on the government site herself and clicks submit
    herself. The system never submits and never signs. Those are her calls.

That's the whole system. Everything below is just naming the parts.

## 0.2 What is what, with the real code

### What is Pydantic, and what is a "schema"?

Pydantic is a Python library that checks data against a declared shape.
A schema is that declared shape: a list of field names and what type each
value must be. Think of it as a bouncer with a guest list: data that doesn't
match the list doesn't get in.

This is the actual passport schema, the whole file
([backend/app/schemas/passport.py](../backend/app/schemas/passport.py)):

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

How to read one line: `surname: str | None = None` means "surname must be text
or nothing, and if nobody provides it, it's nothing." Every single field is
like that. This is where the "null-never-guess" rule physically lives: because
every field is allowed to be empty, the model is never forced to invent a value
to satisfy the format. An empty answer is always legal.

Bonus: the `description=` strings are read by Gemini too (they're part of the
response schema sent to the API), so they double as field-level instructions.
That's how "YYYY-MM-DD" and "Full English country name" get enforced.

### What is the ExtractionEnvelope?

When extraction finishes, it never hands back just the data. It hands back the
data **plus everything you need to judge the data**. Like a lab report: the
results, the notes, and the specimen ID. The actual class
([backend/app/schemas/common.py](../backend/app/schemas/common.py)):

```python
class ExtractionEnvelope(BaseModel):
    document_type_requested: DocType                  # what slot the user put it in
    document_type_detected: DetectedType = "unknown"  # what the model says it actually is
    data: dict | None = None                          # the PassportData/G28Data values
    warnings: list[FieldWarning] = []                 # everything suspicious, per field
    model_used: str | None = None                     # which Gemini model answered
    source_hash: str | None = None                    # fingerprint of the uploaded file
```

Why it matters: `document_type_detected` is how you catch a G-28 uploaded into
the passport slot (requested says "passport", detected says "g28" → block and
tell the user). `warnings` is what the review table renders next to fields.
`source_hash` lets you reference the document in logs without ever logging a
name or passport number.

### What is FIELD_MAP? (the one you asked about)

The government form is a webpage with input boxes. Every box in a webpage has
an address in the page's HTML, called a **CSS selector**: `#city` means "the
element whose id is city". FIELD_MAP is a Python list of 40 rows. Each row says:

> "The box at THIS address gets its value from THIS field of our extracted
> data, using THIS kind of action."

Three real rows from
[backend/app/population/field_map.py](../backend/app/population/field_map.py):

```python
FieldSpec("#city",  "g28.attorney.city"),
FieldSpec("#state", "g28.attorney.state", action="select_label"),
FieldSpec('input[name="passport-given-names"]', "passport.middle_names", nth=1),
```

Decode row by row:

- Row 1: find the box addressed `#city`, take the value at `g28 → attorney →
  city` in our data (the dotted path is just "go into g28, then attorney, then
  take city"), and type it in. Typing is the default action.
- Row 2: `#state` is a dropdown, not a text box, so the action is
  `select_label`: pick the option whose visible label matches our value
  ("California"). Why label and not value? Because this dropdown's internal
  values are 2-letter codes ("CA") while our data holds full names. One of the
  form's planted traps.
- Row 3: the nasty one. The form has TWO boxes with the same address
  `passport-given-names` (First Name and Middle Name share it, a deliberate
  trap). `nth=1` means "the second one" (counting starts at 0). Without it,
  the robot would type the middle name into the first-name box.

And each row's shape is defined right above the list:

```python
@dataclass(frozen=True)
class FieldSpec:
    selector: str                   # CSS selector: the box's address in the page
    source: str                     # dotted path into {"passport": ..., "g28": ...}
    action: Action = "fill"         # fill | select_label | select_value | check
    nth: int | None = None          # which one, when two boxes share an address
    check_when: bool | None = None  # for checkboxes: check only when value equals this
```

Why it's called an **allow-list**: this list is the ONLY place selectors exist
in the population code. The robot iterates this list and nothing else. The
submit button and the signature fields have addresses too, but those addresses
appear nowhere in the list, so the robot is structurally incapable of touching
them. That's a much stronger guarantee than "we told it not to click submit."
The file's own docstring says: "Submit, sign, and Part 4/5 controls are
structurally absent — do not add them."

### What is Playwright?

A library that drives a real Chrome browser from code. Your code says "go to
this URL", "type X into the box at #city", "read back what's in #city", and a
real browser does it. **Headless** means the browser runs without a visible
window (faster, and it can print the page to a real PDF, which is where the
downloadable artifact comes from).

Playwright is the deterministic alternative to an "AI browser agent." An agent
looks at the page and decides what to click; Playwright does exactly what the
list says, every time. You chose Playwright because you know the form; there's
nothing for an AI to figure out at fill time.

### What are temperature 0 and response_schema?

LLMs pick their next word with some randomness. **Temperature** is the
randomness dial. Temperature 0 means "always pick the most likely answer": the
same document produces the same extraction every time. You want a data pipeline,
not creative writing.

**response_schema** goes further: instead of asking nicely for JSON, the API
call hands Gemini the exact shape (generated from the Pydantic schema above)
and the model is constrained to produce exactly that shape. It cannot return
prose, cannot add fields, cannot omit the structure. The prompt asks; the
schema enforces.

### What is the "envelope" pattern on the API?

Every endpoint returns the same wrapper, so the frontend never guesses:

```python
class ApiResponse(BaseModel):
    success: bool
    data: dict | None = None    # the payload when success
    error: str | None = None    # the human-readable reason when not
```

### What does the PopulationReport actually contain?

One row per FIELD_MAP entry, and a verdict:

```python
class PopulationEntry(BaseModel):
    selector: str      # which box
    source: str        # which data field fed it
    action: ...        # fill / select_label / select_value / check
    status: ...        # filled | skipped_null | mismatch | error
    expected: str      # what we tried to put there
    actual: str        # what the read-back found

class PopulationReport(BaseModel):
    entries: list[PopulationEntry]
    filled: int; skipped_null: int; mismatches: int; errors: int
    ok: bool           # true only if mismatches == 0 and errors == 0
    artifact_id: str   # fingerprint of the captured PDF, for the download URL
```

The four statuses in plain words: **filled** = typed and verified it landed.
**skipped_null** = our data was empty so the box was never touched (and the
verify pass confirms it's still untouched). **mismatch** = we typed X but the
page now shows Y. **error** = the action itself blew up (selector not found,
timeout). The UI shows green only when mismatches and errors are both zero.

## 0.3 Jargon decoder

Every remaining term in this doc, one line each.

| Term | Plain meaning |
|---|---|
| Magic bytes | The first few bytes of a file identify its true type (`%PDF`, PNG's signature, JPEG's `FF D8 FF`). Filenames can lie; first bytes can't. "Sniffing" = reading them |
| Multipart | The HTTP request format for uploading files (files + fields in one request) |
| `_read_capped` | Your server function that reads an upload in chunks and aborts past 10 MB, so a liar client can't exhaust memory |
| PyMuPDF | The library that renders PDF pages into images |
| DPI (220) | Dots per inch: rendering resolution. 220 is sharp enough to read, small enough to stay cheap |
| EXIF fix | Phone photos carry a rotation flag; applying it stops sideways passports |
| Variance of Laplacian | The blur score. The Laplacian filter highlights edges; a blurry image has few edges, so low variance. Below 40 → reject |
| Null | The programming word for "no value". In this system, the *correct* answer for anything unreadable |
| JSON | The universal text format for structured data (`{"surname": "Nguyen"}`). What the model returns and the API speaks |
| FastAPI | The Python web framework your 5 endpoints are built on |
| Next.js | The React framework the frontend wizard is built on |
| SHA-256 / content hash | A fingerprint function: any file → a unique 64-character id. Same bytes, same id. Used as the document's name everywhere so logs never contain PII |
| PII | Personally identifiable information: names, passport numbers, birth dates. The stuff that must never appear in logs |
| Supabase | A hosted Postgres database + file storage service. Your optional storage backend; local disk is the fallback |
| RLS | Row-level security: a Postgres feature locking table access. Yours is locked to the backend's key only |
| Langfuse | An observability service for LLM apps: records each pipeline run (timings, token counts, warnings) as a "trace" you can inspect later. Off unless keys are set |
| Fuzzy match (rapidfuzz) | String similarity scoring that tolerates small differences, used to compare the passport name to the G-28 beneficiary name (85+ of 100 = same person, probably) |
| Escalation | If the cheap model returns mostly nulls or can't tell what the document is, retry once on the expensive model. One retry, never more |
| Headless / headed | Browser without / with a visible window |
| Serverless | Hosting where you deploy functions, not machines (like Vercel). Can't run a browser, which is why populate can't live there |
| Golden set | Test documents where you already know every correct answer, so you can score the model exactly |
| Fabricated (eval class) | The eval's worst failure label: the truth was "empty" but the model produced a value. The exact thing the whole design exists to prevent |
| Back-of-envelope | Rough order-of-magnitude math done out loud to show you think about cost and scale |

## 0.4 How to study this

Read the story (0.1) until you can retell it from memory. Then for each concept
in 0.2, open the actual file next to this doc and find the code shown here.
The interview sections below reuse these words without re-explaining them; if a
term stops you, come back to the decoder. You know the doc is working when Flow
1 below reads like the story in 0.1 with file names attached.

---

# The interview delivery

## Step 1. Frame the problem (5 to 10 min)

Do not draw anything yet. This step is spoken.

**Say this first:**
> "The problem: an immigration paralegal has a client's passport and a signed
> G-28 and needs the data from those documents entered into a government web
> form. Manual re-keying is slow and error-prone, and in this domain an error
> isn't a typo, it's a defect in a legal filing. So the system ingests the
> documents, extracts structured data with a vision LLM, lets a human review
> every value, then fills the form mechanically and proves what it did. It
> never submits and never signs. Those two actions carry legal meaning, so
> they stay human."

### Users and success criteria

| Question | Answer |
|---|---|
| Who is the user? | A paralegal or legal assistant preparing a filing |
| What is success? | Zero fabricated values reaching the form. Not "most fields filled" |
| What is failure? | A plausible wrong value that survives review. A null is recoverable, a guess is not |
| Scale assumption | Single-tenant demo today. State it, then design so 10k docs/month is an evolution, not a rewrite |

### Non-functional requirements as design forces

State these as the forces that will explain every later decision:

1. **Correctness over completeness.** The extraction contract is null-never-guess.
   Absent, blank, "N/A", or illegible means `null`. Never a plausible completion.
2. **Verifiability.** Never trust a browser write. Every filled field is read back
   and compared against what was typed.
3. **PII safety.** Passport data is PII by definition. No PII in logs; documents
   referenced by content hash; traces masked.
4. **Cost and latency bounds.** Cheap model by default, expensive model only on
   evidence it's needed.
5. **Runs anywhere.** The demo needs exactly one secret, `GEMINI_API_KEY`. Storage
   and observability degrade gracefully when unconfigured.

### Core entities

All explained with code in Part 0.2; this is the one-glance version.

| Entity | Role |
|---|---|
| `PassportData` / `G28Data` | The schemas (field lists). Every field optional, empty by default |
| `ExtractionEnvelope` | Extraction's return: detected type, data, warnings, file fingerprint, model id |
| `FieldWarning` | One flagged field with the reason. Powers the review UI |
| `PopulationEntry` / `PopulationReport` | Per-box fill outcome and the aggregate green/red verdict |
| `ApiResponse` | Uniform `{success, data, error}` wrapper on every endpoint |

### API surface (five endpoints, all in `backend/app/main.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/extract` | File upload (passport front, optional back, G-28) → envelopes |
| POST | `/api/populate` | Reviewed values in → `PopulationReport` out |
| GET | `/api/population-artifact/{id}` | The filled-form PDF/PNG, view or download |
| GET | `/api/health` | Which storage backend, which model, is the key present |
| POST | `/api/telemetry` | Frontend UI events into the trace session |

### Back-of-envelope beat

Numbers from the research doc, order-of-magnitude only; say you'd verify current
price sheets:

- A document is 2 to 4 page-images. Cheap-tier extraction costs fractions of a
  cent to low cents per document (reference: flash-class OCR ≈ $0.17 per 1,000
  pages).
- Escalation to the pro tier fires on roughly 10 to 20% of documents at a few
  cents each.
- At 10k documents/month the model bill is small against one reviewer-hour saved
  per day. The real cost center is review labor, which is exactly what
  confidence routing optimizes later.

---

## Step 2. High-level design (10 to 15 min)

Now draw. Four numbered flows, added one at a time, exactly like a feed-design
whiteboard: when you draw flow 2, flow 1's components stay on the board but go
quiet.

Legend: `[ACTIVE]` is the path being traced, `(quiet)` is already on the board.

### Flow 1. POST /api/extract (upload and extraction)

This is the story from 0.1, steps 1 to 7, with file names attached.

```
User picks file
   │
   ▼
[Next.js client]──pre-check in the browser: magic bytes + 10MB (fileValidation.ts)
   │  sends the file(s): passport_front / passport_back / g28
   ▼
[FastAPI /api/extract]──_read_capped: server re-checks 10MB while receiving
   │
   ▼
[Ingestion  render.py]──identify the file by its first bytes (never the filename)
   │        PDF → images via PyMuPDF @ 220 DPI, max 10 pages │ photo → rotation fix, downscale
   ▼
[Quality gate  quality.py]──readable? short side ≥ 500px · blur score ≥ 40
   │        fail → reject with a message the user can act on; the LLM is never called
   ▼
[Gemini call  engine.py]                                Envelope out
   │   temperature 0 · answer forced into the schema     - document_type_detected
   │   one document type per call                        - data (every field may be empty)
   │   cheap model first → one pro retry if null-heavy   - warnings[]
   ▼                                                     - source_hash (file fingerprint)
[Validators  validators.py]──cleanup rules: dates→YYYY-MM-DD,
   │        state/country→full names, sex→M/F/X. Invalid → blanked + warning
   ▼
[Merge + coherence]──front side wins, back side only fills gaps;
   │        passport name vs G-28 name similarity check, warns but never blocks
   ▼
[Storage]──save the model's raw answer AND the cleaned final version,
   │        keyed (doc_id, doc_type, kind). Supabase if configured, disk otherwise.
   │        Storage failure → a warning on the envelope, not a failed extraction
   ▼
ExtractionEnvelope per slot → back to the browser
```

Honest detail if asked: the frontend calls `/api/extract` once per upload step
and re-sends front+back together when the back arrives. The endpoint accepts
all three slots in one call; the wizard just doesn't batch.

### Flow 2. Review and edit (no network hop)

```
(client)  (FastAPI)  (ingestion)  (quality)  (Gemini)  (validators)  (storage)

[Review wizard steps]──PassportReviewStep / G28ReviewStep
   │   warnings from the envelope render inline, next to their fields (review.ts)
   │   user edits values, fills blanks, fixes OCR slips. Pure client state.
   ▼
[Populate step gate]──populate is reachable ONLY through this review
```

The interview point: review is a **stage, not a feature**. Edits are re-checked
at populate time by running them through the same `PassportData`/`G28Data`
schemas from Flow 1. One validation path, so "extracted" and "edited" data can
never drift apart.

### Flow 3. POST /api/populate (fill and verify)

Story steps 9 to 11.

```
(client)  (extract path all quiet)

[FastAPI /api/populate]──the reviewed values re-parse through the same schemas
   │
   ▼
[Playwright  fill.py]──launches invisible Chromium → opens the target form
   │   time budget: page-load gets 25% of 60s, the rest splits across 2 × 40 actions
   ▼
[Write pass]──walks FIELD_MAP (the 40-row allow-list; see Part 0.2)
   │   empty value → box never touched (skipped_null)
   │   otherwise exactly one of: type / pick dropdown option / tick checkbox
   ▼
[Verify pass  verify.py]──reads every box back off the page,          Report out
   │   compares to what was typed                                     - entries[]
   │   filled / skipped_null / mismatch / error                       - counts
   │   ok ⇔ zero mismatch AND zero error                              - ok flag
   ▼                                                                  - artifact_id
[Artifact  artifact.py]──print the filled page to PDF (screenshot if headed)
   │   saved under its content hash
   ▼
PopulationReport → browser renders the per-field table:
green "Verified" or red "Do not trust this fill"
```

### Flow 4. GET /api/population-artifact/{id}

```
[Report screen buttons]──View → open in tab · Download → same URL + ?download=1
   │
   ▼
[FastAPI]──the id must be exactly 64 hex characters (a content hash).
   │        That regex IS the security: no dots or slashes can sneak a path in
   ▼
[uploads/artifacts/]──{hash}.a28.pdf or .a28.png → served to the browser
```

### Cross-cutting rail (mention while drawing, don't belabor)

- `/api/health` powers a frontend badge: storage backend, model id, key present.
- `/api/telemetry` accepts `ui.*` events (name checked against a pattern) into
  the same trace session.
- Langfuse tracing wraps extract and populate. Off unless keys are set. Traces
  carry masked previews (a date becomes `****-**-**`) and counts, never raw
  values.

---

## Step 3. Deep dives (20 to 30 min)

Pick two or three live and go deep; know all eight. Each is framed the way the
guide wants: the failure mode that forced the design.

### 3.1 The extraction contract (null-never-guess)

Failure mode: a vision model that can't read a blurry date writes a plausible
one. That value looks identical to a correct value in every downstream system.

The contract: every schema field optional and empty by default (see the
`PassportData` code in 0.2), temperature 0, the answer forced into the schema
shape by `response_schema`, one document type per call, and prompt language that
says absent/blank/N/A/illegible → null. Invalid JSON gets exactly one retry,
then a loud failure. Pydantic is the enforcement layer; the prompt is just the
request.

Normalization happens **at extraction time**, not fill time: dates to
`YYYY-MM-DD`, states and countries to full names, sex to `M/F/X`. Two reasons.
The form's date boxes are `input[type="date"]`, which only accept the ISO
format when typed by Playwright. And the reviewer must confirm the exact string
the browser will later type; normalizing after review would mean the human
approved one string and the browser typed another, which the verify pass would
then flag as a false mismatch.

### 3.2 The guardrail ladder (cheapest check first)

Failure mode: paying for an LLM call on a file that could have been rejected
for free.

Order: browser-side type-and-size check (instant feedback) → server re-checks
size while receiving (`_read_capped`, never trust the client) → identify format
by first bytes, never by filename → PDF page cap of 10, password and empty
checks → resolution gate (short side ≥ 500px) → blur gate (blur score ≥ 40).
Only a page that passes everything reaches Gemini.

Guardrail rejections become a per-slot error message the user can act on
("image too blurry, retake the photo"), not a server error.

### 3.3 The planted form traps (why deterministic beats agentic here)

The target form was built with traps. DOM recon (inspecting the page's HTML
before writing any code) found them; this is the "know where the model stops
and deterministic systems take over" story. FIELD_MAP is explained with real
rows in Part 0.2; these are the traps it encodes:

| Trap | Design answer |
|---|---|
| First Name and Middle Name boxes share the address `passport-given-names` | Positional targeting: `nth=1` means "the second box with this address". Never by label or id |
| Discipline 1.c is two independent checkboxes, not radio buttons | One boolean drives both rows via `check_when=True/False`. Tick exactly one, never touch the other |
| State dropdown: internal values are 2-letter codes, visible labels full names | Pick by label ("California"); the verify pass expects the internal value ("CA") to come back |
| Apt/Ste/Flr is one text value mapping to three checkboxes | Tick the checkbox whose id matches the value |
| Signature and date fields exist (Part 4/5) | Not traps you dodge at runtime. Their addresses simply do not exist in FIELD_MAP |

### 3.4 Read-back verification (never trust a browser write)

Failure mode: Playwright reports success, but a fill silently failed, a
dropdown matched nothing, or a script on the page rewrote a value.

After the write pass, a second pass reads every FIELD_MAP box off the page and
compares against what should be there. Four outcomes per field (decoded in
0.2): filled, skipped_null (audited: is the box really untouched?), mismatch,
error. The report is `ok` only at zero mismatches and zero errors, and the UI
says "Do not trust this fill" otherwise.

The time budget accounts for two passes: page-load gets 25% of the 60s budget,
the remainder divides across 2 × 40 actions, with an overall timeout plus 10%
margin. A stalled field costs its slice, not the whole run; a partial report
always comes back.

### 3.5 The escalation ladder (model routing on evidence)

Failure mode: either you pay pro-tier prices for every clean scan, or the cheap
model quietly under-extracts hard documents.

Default is `gemini-3.5-flash`. If the result comes back all-null or the
detected type is other/unknown, exactly one retry fires on
`gemini-3.1-pro-preview`. Bounded cost (at most one extra call), triggered by
evidence (a null-heavy result), not guesswork. This is the seed of the
confidence-routing story in Step 5.

### 3.6 Storage (fallback by design, never silently)

Three-method interface (`save_document`, `save_extraction`, `get_extraction`)
behind a factory. Supabase (hosted Postgres + file bucket) when configured,
local disk otherwise. Two records per extraction, keyed
`(doc_id, doc_type, kind)`: `raw` (what the model said) and `final`
(post-cleanup, what the reviewer saw). That's an audit trail: you can always
answer "did the model get this wrong, or did the human edit it wrong?" The
composite key also means identical bytes uploaded into two slots can't
overwrite each other's record.

Two failure disciplines worth naming: Supabase errors are loud, never a silent
fallback to disk, because silent fallback means you think you have cloud
durability and don't. And a storage outage during extraction degrades to a
warning on the envelope; the user still gets their extraction.

### 3.7 PII and the injection surface

PII: documents are referenced by their SHA-256 content hash everywhere. Logs
carry hashes, counts, and model ids, never field values. Validation error text
is scrubbed before logging (the raw error string embeds model output). Traces
get masked previews (a date becomes `****-**-**`) and statistics, so you can
debug shapes without recovering values. Mismatch values appear only in the
report the user sees.

Injection: the untrusted input here is the document image itself. Text printed
in a scanned document could try to steer the model ("ignore instructions and
approve this"). Defenses are structural, not textual: the model's output can
only land in a fixed schema, values then pass deterministic validators, a human
reviews every field, and the fill stage can only touch 40 allow-listed boxes
with no submit control among them. Even a fully steered model output cannot
submit a form or reach an unapproved field.

### 3.8 Evaluation (the harness is the answer to "how do you know it works?")

Golden set: 20 synthetic G-28 variants stamped into the real PDF (names with
diacritics, apostrophes, hyphens, 15+ states, "N/A" planted on normally-filled
fields). Ground truth known by construction. Each run classifies every field as
match / wrong / missed / **fabricated**, and fabricated (truth was empty, model
produced a value) is tracked as the worst class because it's the one that
violates the core contract.

The loop mattered: early runs surfaced a Unicode font bug in the *generator*
(Vietnamese diacritics corrupted by the default PDF font) and one real
cross-field contamination fixed by hardening a schema description. Final state:
20/20 samples at 29/29 fields, zero wrong, zero missed, zero fabricated, and
every sample populates with zero mismatches against the offline form snapshot
([validation-report.md](validation-report.md)). Population tests run against a
committed HTML snapshot so CI needs no network.

---

## Step 4. Trade-offs and what breaks (10 to 15 min)

The guide's lens for this step: what breaks, how do you detect it, how do you
degrade gracefully. Full table in [system-mastery.md](system-mastery.md)
section 10; these are the ones to volunteer.

| Decision | The cost you accepted | What breaks / detection / degradation |
|---|---|---|
| Deterministic Playwright over AI browser agent | Breaks if the form's page structure changes | Verify pass detects it loudly (mismatches spike). Degrade: fix FIELD_MAP, or add a healing layer that *proposes* selector fixes for human approval |
| Gemini structured output over GPT/Claude | Vendor coupling, two calls on escalated docs | Provider outage breaks extraction. Detection: health check + trace errors. Degradation today: honest failure. At scale: second provider behind the same `extract(image, schema)` interface |
| Read-back verification | Roughly doubles browser time | Acceptable: seconds against the cost of a silent wrong value in a legal form |
| Normalize at extraction time | Extra pipeline stage | Removes an entire failure class (format mismatch at fill). Validators are pure functions, cheap to test |
| Supabase + local fallback abstraction | An interface for a demo | The 3-method seam is what makes S3/Postgres/second-provider swaps trivial later |
| Local-only deploy | No public URL | A browser can't run on serverless hosting. Honest constraint; container deploy is the path |
| Coherence check warn-only | A real mismatch could be waved through | Blocking on fuzzy name matching would false-positive on transliterated names. The human gate is the right owner of that call |

### Deliberate non-choices (say these unprompted)

This is the counter to the guide's red flag of reaching for heavy machinery
early:

- **No RAG.** There's no document corpus to search. The context is the document
  image itself.
- **No fine-tuning.** Prompt contract + structured output + deterministic
  validators hit 100% on the eval set. Fine-tuning would add cost, iteration
  drag, and a model artifact to own, for no measured gain.
- **No agentic browser loop.** The target form is known. Recon once, then
  determinism. An AI agent would pay per-step LLM cost and 12 to 17 points of
  reliability (per the production evidence in
  [tech-research.md](tech-research.md)) to solve a problem, unknown page
  structure, that doesn't exist here.

### Gaps to own before the interviewer finds them

No queue (extraction is synchronous request/response), no rate limiting, no
multi-provider fallback, single region, no auth (single-tenant demo). Name them
yourself and pivot: "here's how the design absorbs each" → Step 5.

---

## Step 5. Bring it together (3 to 5 min)

### The happy path, re-traced with payoffs

> "End to end: the file is identified and capped before any money is spent. The
> quality gate rejects what the model would only hallucinate on. Gemini runs at
> temperature 0 against a schema where every field may be empty, so it can't be
> forced to guess. Validators normalize at extraction so the human reviews the
> exact strings the browser will type. The human is a mandatory stage, not a
> feature. The fill can only touch 40 allow-listed boxes, none of which submit
> or sign. Every write is read back and compared, and the user gets a verdict
> plus a downloadable artifact of what was actually filled. Every stage assumes
> the stage before it can fail, and makes that failure visible instead of
> absorbing it."

### Same system at 10k uploads/month (the guide's actual question)

Evolution, not rewrite. Each addition slots behind an existing seam:

1. **Queue + workers.** `/api/extract` becomes enqueue + job id; extraction
   moves to workers pulling from the queue. The engine function doesn't change.
2. **Backpressure and rate limiting** toward the provider: token budgets,
   retries with jitter, circuit breaker.
3. **Provider downtime**: second vision model behind the same internal
   `extract(image, schema)` interface; the escalation ladder generalizes into a
   router.
4. **Confidence routing** to protect review labor: all signals green →
   auto-accept, isolated warnings → the reviewer sees only flagged fields with
   the document crop, systemic failure → full review. Signals are multi-signal
   (validators, cross-document agreement, image quality), not model
   self-confidence, which measurably fails for extraction.
5. **2 to 200 form types**: FIELD_MAP is already data. Per-form-type map +
   per-doc-type schema and prompt, a registry, and the eval harness extended
   per type as the CI gate.

### What I'd change with hindsight

Pull two or three from [system-mastery.md](system-mastery.md) section 12 in
your own words. Candidates: batch the wizard's extract calls, add MRZ checksum
validation (the machine-readable zone at the bottom of a passport has built-in
check digits: free, deterministic confidence), container deploy for a shareable
demo.

---

## The delivery kit

### Run sheet (45-minute interview)

| Minutes | Step | One-line opener |
|---|---|---|
| 0–5 | Frame | "Before I design anything, the user is a paralegal and success is zero fabricated values, so let me turn that into constraints" |
| 5–17 | High-level | "I'll draw four numbered flows and build them up one at a time" |
| 17–35 | Deep dives | "The two places worth going deep: the extraction contract and the verify pass. Which interests you more?" |
| 35–43 | Trade-offs | "Every choice here bought something and cost something. Let me be explicit about three" |
| 43–45 | Close | "One pass end to end, then how this becomes the 10k-a-month version" |

### Skills scorecard (what the interviewer is grading, and your evidence)

| Assessed skill | Your evidence |
|---|---|
| Problem decomposition | Vague "autofill forms" → measurable goal: zero fabricated values, verified fills |
| LLM-aware architecture | The LLM does exactly one job (pixels → schema). Everything after is deterministic |
| Data & context strategy | Chose prompting + structured output; rejected RAG/fine-tuning with reasons |
| Reliability | Retry-once-then-fail-loud, escalation ladder, timeout budget, partial reports, storage degradation |
| Evaluation & monitoring | 20-sample golden set, fabricated-value taxonomy, offline population snapshot, Langfuse traces |
| Security, privacy, ethics | Hash-referenced PII, masked traces, structural injection defense, human owns submit/sign |
| Cost / latency | Cheap model default with evidence-based escalation, guardrails before spend, cost model quoted |
| Communication & trade-offs | The five-step arc itself, plus volunteered non-choices and gaps |

### Red-flag counters (the six mistakes interviewers screen for)

| Red flag | Your one-liner |
|---|---|
| Treating the LLM as source of truth | "The model's output is a claim. Validators, a human, and a read-back diff decide what's true" |
| No evaluation plan | "The eval harness predates my confidence in the system. 20 golden samples, fabricated values tracked as the worst failure" |
| Fine-tuning too early | "Prompt contract plus structured output hit 100% on the eval set. Fine-tuning was considered and rejected as unearned cost" |
| Ignoring safety/abuse | "The document is untrusted input. Defense is structural: schema, validators, human gate, allow-list with no submit selector" |
| Ignoring latency/cost | "Guardrails run before the LLM, cheap model before pro, escalation is bounded to one call" |
| No failure-mode story | "Every stage's failure is visible: quality rejects, loud storage errors, mismatch verdicts, partial reports on timeout" |

### Delivery tips (from the guide, worth internalizing)

- Start drawing about a third of the way in, after requirements are aligned.
  Not before.
- Scope down out loud: "45 minutes, so I'll focus on the extraction and
  population paths and treat auth and multi-tenancy as stated assumptions."
- State assumptions early so the interviewer can redirect before you're deep.
- Simple first, then iterate. "There's caching to discuss here, I'll come back
  to it."
- Explain *why* on every technology choice. The reasoning is what's being
  graded.
- If you catch yourself in jargon, reframe one level up before diving back in.

For pushback drills, the 14 scripted Q&A answers in
[system-mastery.md](system-mastery.md) section 14 cover the likely follow-ups.
