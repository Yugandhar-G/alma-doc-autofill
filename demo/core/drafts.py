"""DraftAction store + guarded state machine — CLAUDE_WORKPLAN.md §1.2 + §4.2.

State transitions: pending → approved → sent, or pending → rejected.

mark_sent enforces "no send without approval" TWICE (guardrail §4.2):
  1. a Python assertion that the current state is `approved`;
  2. a guarded `UPDATE ... WHERE state='approved'` whose rowcount must be 1 —
     if it is 0, we raise instead of silently no-op'ing;
  3. (belt and suspenders) the message_sent ledger insert is additionally
     blocked by a DB trigger unless the draft reached approved/sent.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from .models import DraftAction, DraftGrounding, DraftTo


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_draft(conn: sqlite3.Connection, draft: DraftAction) -> DraftAction:
    """Persist a draft. State ALWAYS starts `pending`, whatever the input said."""
    draft = draft.model_copy(update={"state": "pending"})
    conn.execute(
        "INSERT INTO draft (id, case_id, kind, trigger, to_name, to_channel_address, "
        "subject, body, grounding, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            draft.id,
            draft.case_id,
            draft.kind,
            draft.trigger,
            draft.to.name,
            draft.to.channel_address,
            draft.subject,
            draft.body,
            json.dumps(draft.grounding.model_dump()),
            draft.state,
        ),
    )
    conn.commit()
    return draft


def get_draft(conn: sqlite3.Connection, draft_id: str) -> DraftAction | None:
    row = conn.execute("SELECT * FROM draft WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        return None
    return DraftAction(
        id=row["id"],
        case_id=row["case_id"],
        kind=row["kind"],
        trigger=row["trigger"],
        to=DraftTo(name=row["to_name"], channel_address=row["to_channel_address"]),
        subject=row["subject"],
        body=row["body"],
        grounding=DraftGrounding.model_validate(json.loads(row["grounding"])),
        state=row["state"],
    )


def _require_draft(conn: sqlite3.Connection, draft_id: str) -> DraftAction:
    draft = get_draft(conn, draft_id)
    if draft is None:
        raise LookupError(f"draft {draft_id!r} does not exist")
    return draft


def _guarded_transition(
    conn: sqlite3.Connection, draft_id: str, expected: str, new: str
) -> DraftAction:
    """UPDATE ... WHERE state=expected; rowcount 0 ⇒ raise. Never a silent no-op."""
    draft = _require_draft(conn, draft_id)
    if draft.state != expected:
        raise ValueError(
            f"draft {draft_id!r} is {draft.state!r}, expected {expected!r} "
            f"to transition to {new!r}"
        )
    cur = conn.execute(
        "UPDATE draft SET state = ? WHERE id = ? AND state = ?",
        (new, draft_id, expected),
    )
    if cur.rowcount != 1:
        conn.rollback()
        raise ValueError(
            f"guarded transition {expected!r}→{new!r} for draft {draft_id!r} "
            f"affected {cur.rowcount} rows (expected 1)"
        )
    conn.commit()
    return _require_draft(conn, draft_id)


def approve_draft(conn: sqlite3.Connection, draft_id: str) -> DraftAction:
    """pending → approved (A produces draft.approved separately)."""
    return _guarded_transition(conn, draft_id, "pending", "approved")


def reject_draft(conn: sqlite3.Connection, draft_id: str) -> DraftAction:
    """pending → rejected."""
    return _guarded_transition(conn, draft_id, "pending", "rejected")


def mark_sent(
    conn: sqlite3.Connection,
    draft_id: str,
    *,
    mocked: bool,
    channel: str | None = None,
) -> DraftAction:
    """approved → sent, then write the guarded message_sent ledger row.

    Enforcement layer 1: assert current state is `approved`.
    Enforcement layer 2: guarded UPDATE ... WHERE state='approved', rowcount==1.
    Enforcement layer 3: the message_sent trigger aborts if the draft is not
    approved/sent (see db.py).
    """
    draft = _require_draft(conn, draft_id)
    assert draft.state == "approved", (
        f"mark_sent requires state 'approved', got {draft.state!r} "
        f"for draft {draft_id!r} (guardrail §4.2)"
    )

    cur = conn.execute(
        "UPDATE draft SET state = 'sent' WHERE id = ? AND state = 'approved'",
        (draft_id,),
    )
    if cur.rowcount != 1:
        conn.rollback()
        raise ValueError(
            f"mark_sent guarded update for draft {draft_id!r} affected "
            f"{cur.rowcount} rows (expected 1) — state was not 'approved'"
        )

    conn.execute(
        "INSERT INTO message_sent (id, draft_id, channel, sent_at, mocked) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            f"msg_{uuid4().hex}",
            draft_id,
            channel or draft.kind,
            _now_iso(),
            1 if mocked else 0,
        ),
    )
    conn.commit()
    return _require_draft(conn, draft_id)
