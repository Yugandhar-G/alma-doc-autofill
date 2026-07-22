# yunaki demo — /core contracts

Frozen contracts (CLAUDE_WORKPLAN.md §1) shared by Workstream A (`slack_agent`)
and Workstream B (`validation`/`followup`). **FROZEN after day 0** — a needed
change is a message to the other human, not a silent edit.

## Install
```bash
cd demo && pip install -e .
cp .env.example .env   # fill in; never commit .env
```
Target runtime is Python 3.12; the code is 3.10-compatible so tests run anywhere.

## What's here
- `core/models.py` — pydantic contracts + the single source of every closed enum.
- `core/db.py` — SQLite connection factory + idempotent schema. Guardrails are in
  the DDL: `event.type` / `draft.state` CHECK constraints and a `message_sent`
  ledger whose insert is trigger-blocked unless the draft was approved (§4.2).
- `core/events.py` — append-only event bus + in-process pubsub + replay/query.
- `core/drafts.py` — DraftAction store; `mark_sent` enforces approval three ways.
- `core/sendgate.py` — the LIVE_MODE gate (§4.1). **Every** outbound adapter routes
  through `execute_draft`. Default mock: writes `outbox`, never sends.
- `core/config.py` — `.env` loader for the §1.4 vars.
- `seed/seed_case.py` — idempotent fictional marriage case (Ravi Kumar / Mei Lin).
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
