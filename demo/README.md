# yunaki demo — /core contracts

Frozen contracts (CLAUDE_WORKPLAN.md §1) shared by Workstream A (`slack_agent`)
and Workstream B (`validation`/`followup`). **FROZEN after day 0** — a needed
change is a message to the other human, not a silent edit.

## Install
```bash
cd demo
python3.13 -m venv .venv          # deepagents needs >= 3.11; 3.13 is what we run
.venv/bin/pip install -e ".[dev]"
.venv/bin/pip install -e ../backend   # the kernel deep-agent engine the email
                                       # agent runs on (Gemini); Python >= 3.11
cp .env.example .env              # fill in; never commit .env
```
Run everything through `.venv/bin/python` (`python -m slack_agent.main`, pytest).

## Integrated firm flow (intake_workflow)

`intake_workflow/` is Nanda's intake/case app (ported from
Nanda-Kiran/Yunaki-Yew@beb0f73, Workstream B's lane) living natively in this
package on the ONE shared DB: Slack handoffs open intake cases and put
magic-link portal URLs into `intake.url`; paralegal-accepted answers upsert
the typed `case_history`; red-flag answers surface as `escalation.raised`;
outreach approvals create PENDING DraftActions through the SendgateProvider
(the default provider) — delivery only via Slack approval + LIVE_MODE.

From the repo root: `make flow-smoke` (live end-to-end proof, no creds
needed), `make intake` (staff dashboard + client portal on :8801), or
`make firm-demo` (intake portal + our Slack agent together).

## What's here

### Agents (Workstream A)
- `slack_agent/` — Bolt Socket Mode process: handoff listener, approval buttons,
  escalations, `/yunaki status`, and the **@yunaki mention agent** — a bounded
  deepagents (LangGraph) loop over an allow-listed tool set (case status/timeline,
  Gmail read, `create_email_draft`). The agent has NO send tool: drafting ends in a
  pending DraftAction + Slack approval card; sends happen only via core.sendgate.
- `gmail_agent/` — demo-mailbox Gmail access. Two paths share it:
  the **@yunaki mention agent's** read tools (`client.py`, `reader.py`), and the
  **always-on email agent** (Jul 22 scope change): `auth.py` (OAuth,
  `python -m gmail_agent.auth`), `watch.py` (Gmail `watch()` → Pub/Sub),
  `consumer.py`/`main.py` (streaming-pull runner, history high-water + message
  dedup + own-address loop prevention), `email_agent.py` (a real bounded
  tool-loop that triages + drafts, with a deterministic grounding post-audit),
  `pipeline.py` (emits `email.received` + creates the pending DraftAction +
  `draft.created`), and `sender.py` (`build_gmail_sender()` — the sendgate-invoked,
  thread-aware sender registered by `slack_agent.main`). Cold setup:
  `docs/gmail-agent-setup.md`.
- `agents/` — the reusable agent layer the email brain (and future Slack-side
  brains) build on: `harness.py` runs the yunaki kernel tool-loop with a
  code-owned budget and persists the full transcript (`agent_transcript` aux
  table); `tools_case.py` is the shared read-only case-tool set over /core.

### /core contracts
- `core/models.py` — pydantic contracts + the single source of every closed enum.
- `core/db.py` — SQLite connection factory + idempotent schema. Guardrails are in
  the DDL: `event.type` / `draft.state` CHECK constraints and a `message_sent`
  ledger whose insert is trigger-blocked unless the draft was approved (§4.2).
- `core/events.py` — append-only event bus + in-process pubsub + replay/query.
- `core/drafts.py` — DraftAction store; `mark_sent` enforces approval three ways.
- `core/sendgate.py` — the LIVE_MODE gate (§4.1). **Every** outbound adapter routes
  through `execute_draft`. Default mock: writes `outbox`, never sends.
- `core/config.py` — `.env` loader for the §1.4 vars.
- `core/case_history.py` — shared case-history schema mirrored from the firm's two
  intake questionnaires (petitioner + beneficiary). One current record per
  `(case, role)`; `upsert_history` overwrites on `(case_id, role)`. Records start as
  stubs at handoff carrying the firm case number; Nanda's intake form-submit endpoint
  (Workstream B) calls `upsert_history` to fill them in. `uscis_case_number` +
  `case_status` are enrichment fields (null until the receipt lands, never guessed).
  The slack agent reads history via `get_history`.
- `seed/seed_case.py` — idempotent fictional marriage case (Ravi Kumar / Mei Lin),
  including seeded petitioner + beneficiary case-history records.
- `scripts/check_no_real_pii.py` — pre-commit grep for real client names (§4.4).

## Run
```bash
python -m pytest -q          # contract tests
python -m seed.seed_case     # seed the demo case (idempotent)
```

## Guardrails (non-negotiable, §4)
- `LIVE_MODE=false` default — no real message leaves without a human flipping `.env`.
- No `message.sent` without a prior `draft.approved` — enforced in code AND schema.
- No real PII anywhere — fictional cast only; pre-commit hook greps for real names.
- Secrets only in `.env` (gitignored day 0).
