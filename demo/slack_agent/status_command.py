"""/yunaki status <case> — CLAUDE_WORKPLAN.md §2 item 5 + §4.3.

Fuzzy-matches <case> against case.name (case-insensitive substring) and replies
with a snapshot built ONLY from the DB: stage, checklist completeness, days since
last client activity per intake, next deadline. Any value not on file is
reported as "not on file" — NEVER estimated, and no USCIS timeline is stated from
model knowledge (§4.3). This handler makes no LLM call at all.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

_DONE_STATES = ("uploaded", "accepted")


def _days_since(iso_ts: str | None) -> str:
    if not iso_ts:
        return "not on file"
    try:
        then = datetime.fromisoformat(iso_ts)
    except ValueError:
        return "not on file"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - then).days
    unit = "day" if days == 1 else "days"
    return f"{days} {unit}"


def _match_cases(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    q = query.strip().lower()
    if not q:
        return []
    return conn.execute(
        'SELECT * FROM "case" WHERE lower(name) LIKE ? ORDER BY name',
        (f"%{q}%",),
    ).fetchall()


def _completeness(conn: sqlite3.Connection, intake_ids: list[str]) -> str:
    if not intake_ids:
        return "no checklist on file"
    placeholders = ",".join("?" * len(intake_ids))
    rows = conn.execute(
        f"SELECT state, mandatory_to_file FROM checklist_item "
        f"WHERE intake_id IN ({placeholders})",
        intake_ids,
    ).fetchall()
    if not rows:
        return "no checklist on file"
    total = len(rows)
    done = sum(1 for r in rows if r["state"] in _DONE_STATES)
    mandatory = [r for r in rows if r["mandatory_to_file"]]
    mand_total = len(mandatory)
    mand_done = sum(1 for r in mandatory if r["state"] in _DONE_STATES)
    pct = f"{round(mand_done / mand_total * 100)}%" if mand_total else "not on file"
    return f"{done}/{total} items in ({pct} of mandatory)"


def handle_status(conn: sqlite3.Connection, query: str) -> str:
    """Build the plaintext status reply for a fuzzy case query."""
    matches = _match_cases(conn, query)
    if not matches:
        return f"No case on file matches '{query.strip()}'."
    if len(matches) > 1:
        names = "\n".join(f"• {row['name']}" for row in matches)
        return f"Multiple cases match '{query.strip()}':\n{names}\nBe more specific."

    case = matches[0]
    intakes = conn.execute(
        "SELECT * FROM intake WHERE case_id = ?", (case["id"],)
    ).fetchall()
    intake_ids = [row["id"] for row in intakes]

    lines = [
        f"*{case['name']}*",
        f"Stage: {case['stage']}",
        f"Process type: {case['process_type'] or 'not on file'}",
        f"Checklist: {_completeness(conn, intake_ids)}",
    ]
    if intakes:
        for row in intakes:
            lines.append(
                f"Intake {row['id']}: last client activity {_days_since(row['last_client_activity_at'])} ago"
            )
    else:
        lines.append("Intakes: not on file")
    # No deadline field exists in the model — never estimate a USCIS timeline.
    lines.append("Next deadline: not on file")
    return "\n".join(lines)
