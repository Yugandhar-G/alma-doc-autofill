"""Shared read-only case tools — the agent's window into the /core tables.

Each tool is a kernel ToolSpec (allow-list dispatch, structural grants). Tools
READ the core-owned tables (client, party, case, intake, checklist_item) and
return COMPACT JSON strings of structured facts. Payload discipline (directive):
no raw email bodies ever pass through a tool result — these tools surface firm
facts only.

Grounding ground-truth: list_checklist_items and get_case_snapshot record every
checklist LABEL they surface into transcript.seen_refs, mirroring how the
kernel's corpus tools record doc_ids. The deterministic post-audit
(email_agent.audit_grounding) trusts ONLY those recorded labels — a reply that
names a label no tool surfaced is stripped.

Tools close over the sqlite connection and a CaseScratch (structured facts the
terminal step reads for draft grounding); the ToolContext the kernel passes
carries the transcript + emit only.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

# registry + genai import cleanly on any interpreter that has the yunaki backend
# on the path (they need only google.genai + pydantic-settings, not deepagents).
from google.genai import types as genai_types

from app.kernel.tools.registry import ToolContext, ToolSpec

_MAX_TOOL_CHARS = 4000


@dataclass
class CaseScratch:
    """Structured facts the tools surface, read by the terminal draft step for
    grounding. The transcript remains the AUDIT ground truth; this is a
    convenience carrier for the snapshot + missing labels, not trusted by audit."""

    matched_case_id: str | None = None
    matched_client_name: str | None = None
    case_snapshot: dict[str, Any] = field(default_factory=dict)
    missing_items: list[str] = field(default_factory=list)


def _cap(text: str) -> str:
    return text if len(text) <= _MAX_TOOL_CHARS else text[:_MAX_TOOL_CHARS] + "\n…[truncated]"


def _compact_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _record_ref(transcript: Any, ref: str) -> None:
    """Append a surfaced checklist label to the transcript ground truth
    (deduped, order-preserving) — the audit reads exactly this."""
    if ref and ref not in transcript.seen_refs:
        transcript.seen_refs.append(ref)


def _str() -> genai_types.Schema:
    return genai_types.Schema(type=genai_types.Type.STRING)


def _bool() -> genai_types.Schema:
    return genai_types.Schema(type=genai_types.Type.BOOLEAN)


def _int() -> genai_types.Schema:
    return genai_types.Schema(type=genai_types.Type.INTEGER)


def build_case_tools(conn: sqlite3.Connection, scratch: CaseScratch) -> list[ToolSpec]:
    """Build the four shared case-read tools bound to this run's conn + scratch."""

    async def _lookup_client_by_email(args: dict, ctx: ToolContext) -> str:
        email = str(args.get("email", "")).strip()
        ctx.emit({"type": "tool_call", "node": ctx.node, "tool": "lookup_client_by_email"})
        row = conn.execute(
            "SELECT id, first_name, last_name FROM client WHERE lower(email) = lower(?)",
            (email,),
        ).fetchone()
        if row is None:
            ctx.transcript.log.append("lookup_client_by_email -> no match")
            return _compact_json({"matched": False})
        party = conn.execute(
            "SELECT case_id FROM party WHERE client_id = ? LIMIT 1", (row["id"],)
        ).fetchone()
        case_id = party["case_id"] if party else None
        scratch.matched_case_id = case_id
        scratch.matched_client_name = row["first_name"]
        ctx.transcript.log.append("lookup_client_by_email -> matched client on a case")
        return _compact_json(
            {
                "matched": True,
                "client_id": row["id"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "case_id": case_id,
            }
        )

    async def _get_case_snapshot(args: dict, ctx: ToolContext) -> str:
        case_id = str(args.get("case_id", "")).strip()
        ctx.emit({"type": "tool_call", "node": ctx.node, "tool": "get_case_snapshot"})
        case_row = conn.execute(
            'SELECT name, process_type, stage FROM "case" WHERE id = ?', (case_id,)
        ).fetchone()
        if case_row is None:
            ctx.transcript.log.append("get_case_snapshot -> not found")
            return _compact_json({"found": False})
        intakes = conn.execute(
            "SELECT id, client_id, state, url FROM intake WHERE case_id = ?", (case_id,)
        ).fetchall()
        intake_facts = []
        for intake in intakes:
            items = conn.execute(
                "SELECT mandatory_to_file, state FROM checklist_item WHERE intake_id = ?",
                (intake["id"],),
            ).fetchall()
            intake_facts.append(
                {
                    "intake_id": intake["id"],
                    "client_id": intake["client_id"],
                    "state": intake["state"],
                    "total_mandatory": sum(1 for i in items if i["mandatory_to_file"]),
                    "missing_mandatory": sum(
                        1 for i in items if i["mandatory_to_file"] and i["state"] == "missing"
                    ),
                    "accepted": sum(1 for i in items if i["state"] == "accepted"),
                }
            )
        snapshot = {
            "found": True,
            "case_id": case_id,
            "name": case_row["name"],
            "process_type": case_row["process_type"],
            "stage": case_row["stage"],
            "intakes": intake_facts,
        }
        scratch.case_snapshot = {
            "case_id": case_id,
            "stage": case_row["stage"],
            "process_type": case_row["process_type"],
        }
        ctx.transcript.log.append(
            f"get_case_snapshot -> stage recorded, {len(intake_facts)} intakes"
        )
        return _cap(_compact_json(snapshot))

    async def _list_checklist_items(args: dict, ctx: ToolContext) -> str:
        intake_id = str(args.get("intake_id", "")).strip()
        missing_only = bool(args.get("missing_only", False))
        ctx.emit({"type": "tool_call", "node": ctx.node, "tool": "list_checklist_items"})
        rows = conn.execute(
            "SELECT seq, label, mandatory_to_file, state FROM checklist_item "
            "WHERE intake_id = ? ORDER BY seq ASC",
            (intake_id,),
        ).fetchall()
        items = []
        for row in rows:
            if missing_only and row["state"] != "missing":
                continue
            label = row["label"]
            # Ground truth: this label was actually surfaced by a tool this run.
            _record_ref(ctx.transcript, label)
            if row["mandatory_to_file"] and row["state"] == "missing":
                if label not in scratch.missing_items:
                    scratch.missing_items.append(label)
            items.append(
                {
                    "seq": row["seq"],
                    "label": label,
                    "mandatory": bool(row["mandatory_to_file"]),
                    "state": row["state"],
                }
            )
        ctx.transcript.log.append(
            f"list_checklist_items(missing_only={missing_only}) -> {len(items)} items"
        )
        return _cap(_compact_json(items))

    async def _recent_events(args: dict, ctx: ToolContext) -> str:
        case_id = str(args.get("case_id", "")).strip()
        limit = int(args.get("limit", 10) or 10)
        limit = max(1, min(limit, 50))
        ctx.emit({"type": "tool_call", "node": ctx.node, "tool": "recent_events"})
        rows = conn.execute(
            "SELECT type, ts, actor FROM event WHERE case_id = ? "
            "ORDER BY ts DESC, rowid DESC LIMIT ?",
            (case_id, limit),
        ).fetchall()
        # type/ts/actor only — event payloads may carry ids/derived facts we do
        # not want to re-expose through a tool result.
        events = [{"type": r["type"], "ts": r["ts"], "actor": r["actor"]} for r in rows]
        ctx.transcript.log.append(f"recent_events -> {len(events)} events")
        return _cap(_compact_json(events))

    return [
        ToolSpec(
            name="lookup_client_by_email",
            description=(
                "Look up whether an email address belongs to a client on file. "
                "Returns {matched: bool, ...} with the client's name and case_id "
                "when matched. Use this FIRST to decide if the sender is a client."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={"email": _str()},
                required=["email"],
            ),
            run=_lookup_client_by_email,
        ),
        ToolSpec(
            name="get_case_snapshot",
            description=(
                "Get a structured snapshot of a case by case_id: name, process "
                "type, current stage, and per-intake completeness counts. Use it "
                "to ground a status reply in the case's real stage."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={"case_id": _str()},
                required=["case_id"],
            ),
            run=_get_case_snapshot,
        ),
        ToolSpec(
            name="list_checklist_items",
            description=(
                "List the checklist items for an intake (from get_case_snapshot's "
                "intake_id). Set missing_only=true for only the still-missing "
                "items. Returns each item's verbatim label, mandatory flag, and "
                "state. You may only name items this tool actually returned."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={"intake_id": _str(), "missing_only": _bool()},
                required=["intake_id"],
            ),
            run=_list_checklist_items,
        ),
        ToolSpec(
            name="recent_events",
            description=(
                "List recent events for a case (type, timestamp, actor only), "
                "newest first, to understand what has happened lately. Does not "
                "return message contents."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={"case_id": _str(), "limit": _int()},
                required=["case_id"],
            ),
            run=_recent_events,
        ),
    ]
