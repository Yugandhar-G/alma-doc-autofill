# CLAUDE_WORKPLAN.md — Yunaki Build: Slack Agent + Validation/Follow-up Agent

*This file is read by Claude during coding sessions. It is the project overlay on top of "Claude Working Principles — Yunaki Engineering" (which governs HOW agents work; this governs WHAT is being built and WHO owns what). Where the two conflict, this file wins for scope; the principles win for process.*

---

## 0. Context (read once, don't relitigate)

We are building the first two agents of an **action layer** for a real immigration law firm (Yew Immigration Law Group — design partner). Demo to the firm's principal attorney: **Friday 8:00 AM PT**. Two humans, two workstreams, one repo:

- **Yugandhar** → Workstream A: **Slack integration** (entry + escalation channel)
- **Nanda** → Workstream B: **Validation & Follow-up agent** (intake completeness + client nudging)

Ground truth for all domain facts: `UI_DataModel_Reference.md` (camera-verified), `Isaiah_Workflow_Walkthrough.md`. Do not invent workflow details that contradict those docs.

**Build grade: DEMO.** Correct behavior on the happy path + seeded data beats coverage. Production hardening only where a guardrail (§4) requires it. If a task takes >2h without visible demo progress, stop and flag.

---

## 1. Frozen contracts (commit these FIRST, before any parallel work)

Per the working principles: interfaces freeze before concurrency. These four contracts are the seam between workstreams A and B. **Neither workstream edits them unilaterally after freeze — a needed change is a message to the other human, not a silent edit.**

### 1.1 Event bus (SQLite table `event` + optional in-process pubsub)

Every agent action and every state change is an appended event. Both workstreams write to and read from this one log.

```json
{
  "id": "evt_uuid",
  "ts": "ISO8601",
  "type": "see enum below",
  "case_id": "case_uuid | null",
  "actor": "agent:slack | agent:validation | agent:followup | human:{name} | client",
  "payload": {}
}
```

Event types (closed enum — adding one = contract change):
```
case.handoff_received      # A produces (parsed from Slack)
intake.sent                # B produces
intake.client_activity     # B produces (upload/edit/submit)
intake.validated           # B produces — payload: {complete: bool, missing: [checklist_item_ids]}
draft.created              # A or B produce — payload: {draft_id, kind, channel}
draft.approved             # A produces (approval happens in Slack)
draft.rejected             # A produces — payload: {reason}
message.sent               # infra produces after approved draft executes
followup.due               # B produces (timer fired)
escalation.raised          # B produces → A must surface it in Slack
email.received             # A produces (Gmail push; added Jul 22 scope change — pending Nanda ack)
```

### 1.2 DraftAction (the only path to any outbound message)

```json
{
  "id": "draft_uuid",
  "case_id": "...",
  "kind": "client_email | client_whatsapp | slack_notification | status_reply",
  "trigger": "validation_incomplete | followup_timer | escalation | manual",
  "to": {"name": "...", "channel_address": "..."},
  "subject": "string | null",
  "body": "markdown",
  "grounding": {"missing_items": [], "case_state": {}, "days_since_activity": 0},
  "state": "pending | approved | rejected | sent"
}
```

### 1.3 Minimal case model (shared read, B writes)

```
case(id, name, process_type, stage, created_at)
party(case_id, client_id, role: petitioner|beneficiary)
client(id, first_name, last_name, email, phone, whatsapp)
intake(id, case_id, client_id, url, state: sent|in_progress|submitted|accepted,
       sent_at, last_client_activity_at)
checklist_item(id, intake_id, seq, label, mandatory_to_file, state: missing|uploaded|accepted)
```
Seed data: ONE fictional marriage case ("Ravi Kumar" petitioner / "Mei Lin" beneficiary — never real client names), checklist labels copied verbatim from Alison's real form (see UI_DataModel_Reference §2).

### 1.4 Config / env (single `.env`, never committed)

```
SLACK_BOT_TOKEN=            # A
SLACK_APP_TOKEN=            # A (socket mode)
SLACK_CHANNEL_CASES=        # A — the demo workspace channel
ANTHROPIC_API_KEY=          # A (email triage/handoff parse) + B (draft wording)
LIVE_MODE=false             # global guardrail, see §4.1
DB_PATH=./yunaki.db

# Gmail agent (A — added Jul 22 scope change, pending Nanda ack)
GMAIL_ADDRESS=                    # the DEMO mailbox (never the firm's)
GMAIL_CREDENTIALS_PATH=.secrets/gmail_credentials.json
GMAIL_TOKEN_PATH=.secrets/gmail_token.json
GMAIL_TOPIC=                      # projects/<gcp>/topics/<topic>
GMAIL_PUBSUB_SUBSCRIPTION=        # projects/<gcp>/subscriptions/<sub> (streaming pull)
GOOGLE_APPLICATION_CREDENTIALS=   # ADC key for the Pub/Sub subscriber
```

### 1.5 Directory ownership (disjoint — per working principles §3)

```
/core          — contracts: models, event bus, draft store, config. FROZEN after day 0.
                 Changes require both humans' agreement, committed by whoever owns the change.
/slack_agent   — Yugandhar ONLY. Nanda's agents must not touch.
/validation    — Nanda ONLY. Yugandhar's agents must not touch.
/followup      — Nanda ONLY.
/web           — approval queue UI if needed beyond Slack approval. Default: SKIP — approvals
                 happen in Slack (A's surface). Only build if Slack approval proves insufficient.
/seed          — fictional demo data. Either may add, neither may add real PII.
tests/         — each workstream owns tests matching its dirs; core contract tests frozen with core.
```

Git: **each human works on own branch (`slack-agent`, `validation-agent`), merges to `main` only when the full suite is green.** Your Claude session never commits to `main` directly. Cross-boundary diffs = stop and escalate to the other human — an agent never resolves a two-human design conflict (working principles §3).

---

## 2. Workstream A — Slack Integration (Yugandhar)

### What it is in the demo story
Slack is the firm's existing internal channel (camera-verified: docked on the paralegal's screen; cases arrive as Slack posts from the attorney). Workstream A makes Slack the **input** (case handoff parsing) and the **control surface** (approvals, escalations) — the firm never has to open a new app to supervise the agents.

### Build list, in order
1. **Slack app scaffolding** — Bolt for Python, Socket Mode (no public URL needed for demo). One workspace (create `yunaki-demo` workspace; NEVER install into the firm's real workspace this week).
2. **Case handoff agent.** Watches `#cases` (SLACK_CHANNEL_CASES). When the attorney posts a handoff (demo format: free text like *"New marriage case, adjustment of status. Ravi — ravi.kumar.demo@example.com, spouse Mei — mei.lin.demo@example.com"*), a **kernel deep-agent loop** (backend `app.kernel.agent.run_tool_loop`: deepagents-owned loop, ToolRegistry grants, budget caps, transcript) works the handoff with tools — find existing client, create case/parties/intakes, ask in-thread for missing fields — and emits `case.handoff_received`. **Null over guess:** unparseable field ⇒ null + the agent's ask-in-thread tool, never invented. *(Amended Jul 22: single structured-output parse upgraded to a real agent loop per Yugandhar — agentic baseline paired with kernel guardrails.)*
3. **Approval flow.** Subscribe to `draft.created` events. Post each draft into the case's Slack thread as a message block: trigger line ("Intake untouched 4 days"), draft body, grounding facts (missing items list), and buttons **[Approve] [Edit] [Reject]**. Button handlers update DraftAction state + emit `draft.approved/rejected`. Edit = modal with the draft text.
4. **Escalation surfacing.** Subscribe to `escalation.raised` (B fires after N ignored nudges) → post @-mention in the case thread: "Client hasn't touched intake after 2 reminders — what do you want to do?" with quick actions [Send again] [Call client — assign task] [Pause chasing].
5. **`/yunaki status <case>` slash command** — replies with case snapshot from /core (stage, checklist completeness %, days since client activity, next deadline). This is your "fetch case status & reply" HLD branch, firm-internal version.
6. *(Stretch, only if 1–5 done)* New-client branch from your HLD: unrecognized sender in handoff channel → prompt attorney for a time slot.
7. **@yunaki task agent (added Jul 22, Yugandhar).** Any team member mentions @yunaki in a case thread or channel with a task ("@yunaki look at the case we are working with", "@yunaki draft a mail to the client") → a kernel deep-agent loop works the task with granted tools (case snapshot, checklist, events, thread context, create DraftAction as terminal action) and replies in the thread. Drafts it creates flow through the normal approval buttons — the agent can never send. Answers state only tool-returned facts; "not on file" otherwise.
8. **Approve latency contract (added Jul 22).** Button handlers ack Slack within 3s, always; the actual send (gmail.send with the original threadId + In-Reply-To/References headers, so the reply lands in the client's existing thread from the firm's own address) runs async after the ack, then updates the Slack message, marks the draft sent, and logs the event.

### Definition of done (A)
- From a Slack post → case exists in DB → B's validation runs → draft appears back in the same thread → Approve marks it sent (mock) → event log shows the full chain. Demo-able end-to-end with B stubbed (use a fake `draft.created` emitter until B lands).
- Zero real client data in the workspace; zero messages to any non-demo workspace.

---

## 3. Workstream B — Validation & Follow-up Agent (Nanda)

### What it is in the demo story
The agent that does Isaiah's chasing for him: verifies intake completeness the moment something happens, drafts the "here's what's missing" message, and nudges when nothing happens for N days. Both behaviors were independently requested by the attorney AND the paralegal (see Isaiah_Workflow_Walkthrough §"Follow-Up Reality").

### Build list, in order
1. **Hosted mini-intake** (simplest possible: one FastAPI page per intake URL with the checklist items + upload buttons + free-text fields, writing `intake.client_activity` events). This exists so the demo can show a *live* client interaction. Fields/labels verbatim from the real petitioner form (UI_DataModel_Reference §2). No auth beyond the URL token — demo grade.
2. **Validation agent.** Trigger: `intake.client_activity` (submit or upload). Logic, two layers per the HLD:
   - **Presence check — deterministic code, no LLM.** Diff checklist_item states: which mandatory items are missing. This alone decides `complete: bool`.
   - **Feedback draft — LLM, structured input only.** Input: party first names, missing item labels (verbatim), intake URL, days outstanding. Output: friendly email/WhatsApp text listing exactly the missing numbered items. The model NEVER sees or invents case facts beyond the structured input (working principles §5).
   - Emit `intake.validated` + `draft.created` (kind per channel; default `client_email`, `client_whatsapp` variant if phone present).
   - Complete path: mark intake submitted→accepted (demo skips human accept), emit event; "document population" from your HLD = checklist items flip states + case snapshot updates. (Full form-fill is NOT in scope this week — eImmigration already auto-generates forms; don't rebuild it for the demo.)
3. **Follow-up timer agent.** APScheduler job every 15 min (demo: configurable to 30s for live effect): any intake in `sent|in_progress` with `now - last_client_activity_at ≥ THRESHOLD` (default 3 days; demo: 60 seconds) → `followup.due` → nudge DraftAction. Cadence guard **in code**: max 1 nudge per intake per threshold window; after 2 unanswered → `escalation.raised` (A surfaces it) and stop nudging.
4. **WhatsApp channel = mock.** A `/seed`-styled fake chat pane or simply the draft rendered with kind=client_whatsapp. Do NOT integrate WhatsApp Business API this week (sender approval takes longer than we have).
5. *(Stretch)* Eligibility monitor: nightly job computing `approval_date + 24mo − 90d` (I-751), `+36mo − 90d`, `+60mo − 90d` (N-400) over seeded clients → `draft.created` outreach. Pure date math, zero LLM, ~1 hour — and it's the ONE feature the paralegal explicitly asked for. Build it if follow-up agent lands by Thursday noon.

### Definition of done (B)
- Upload 2 of 5 docs on the hosted intake → within seconds a draft naming exactly the 3 missing items (verbatim labels) exists → visible in Slack thread (A) or, if A not ready, in a plain `GET /drafts` JSON view.
- Let an intake sit past threshold → nudge draft fires once, not repeatedly; second expiry → escalation event.
- Grep-verifiable invariants: no draft text contains an item not in `grounding.missing_items`; no message record exists without `draft.approved` preceding it.

---

## 4. Guardrails — in code, both workstreams, non-negotiable

1. **`LIVE_MODE=false` default.** Every outbound adapter (Slack post to non-demo workspace, email send, WhatsApp) checks it at the execution layer. False ⇒ writes to `outbox` table + renders in UI/Slack-demo-workspace only. Flipping true requires editing `.env` by a human and logs a loud event. (This is the "agent messages a real client" defect class — our worst.)
2. **No send without approval — schema-enforced.** `message.sent` handler requires draft state `approved`; enforce with a code assertion AND a DB check constraint, not convention.
3. **Null over guess** everywhere a model output feeds state: unparseable handoff field ⇒ null + ask; missing case fact in status command ⇒ "not on file," never an estimate. USCIS timelines are NEVER stated from model knowledge.
4. **No real PII in repo, seed data, tests, or demo workspace.** The real recordings/transcripts contain actual client names — those never enter this codebase (the pre-commit guard in `scripts/check_no_real_pii.py` carries the encoded blocklist). Fictional cast only.
5. **Secrets only in `.env`** (gitignored day 0). No token ever pasted into code, tests, or Slack messages.
6. **Cross-boundary escalation.** Claude session in workstream A needing a /core or /validation change: stop, report to Yugandhar → he messages Nanda (and vice versa). Never "quick fix" the other lane.

---

## 5. Verification (scaled to demo week, per working principles §4)

- Each workstream: happy-path integration test (the DoD scenario above, scripted) + unit tests only for the rules with cadence/guard logic (nudge limiter, presence diff, date math). Skip exhaustive coverage.
- Orchestrator (each human's Claude session) independently re-runs the other's DoD script before merge to `main` — trust-but-verify at the human seam, not just the agent seam.
- Thursday evening: one full dry-run, both workstreams together, on the seeded case, timed. Whatever isn't in that dry-run does not get shown Friday.

## 6. What is explicitly OUT of scope this week

eImmigration/MyCase integration (mirror manually-seeded data only) · real WhatsApp API · the approval web UI (Slack IS the approval surface) · form auto-fill · inbox triage of the firm's real info@ · production auth/multi-tenancy. Anything on this list appearing in a plan = scope creep; flag it.

**Scope change (Jul 22, Yugandhar):** Gmail API is now IN scope for Workstream A — the real always-on email agent: Gmail watch() → Pub/Sub topic → streaming-pull consumer (no public URL) → LLM triage → DraftAction → Slack approval buttons → on approve, real send via Gmail API (gmail.send OAuth) gated by LIVE_MODE. Demo mailbox only, never the firm's. Contract deltas (email.received event type, Gmail env vars) pending Nanda ack.
