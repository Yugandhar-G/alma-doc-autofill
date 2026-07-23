"""SQLite aggregate store. FROZEN interface for parallel work.

Cases serialize as one JSON document per row (prototype-scale by design:
the firm runs 3-5 marriage cases/month). Timeline events are append-only
rows — the lawyer-readable audit trail.

All tenancy stays inside the store (firm_id lives on the Case) so a future
router bug can't leak cross-firm data.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from intake_workflow.schemas import Case, Party, TimelineEvent, utcnow


class Store:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            from core.config import get_db_path
            db_path = get_db_path()
        self.db_path = str(db_path)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        # Single shared DB file in the monorepo: request threads, the handoff
        # consumer, and the Slack/Gmail processes all write here. Wait out
        # writer contention instead of failing with SQLITE_BUSY.
        con.execute("PRAGMA busy_timeout=5000")
        return con

    def _init(self) -> None:
        with self._conn() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS iw_cases ("
                "id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS iw_timeline ("
                "id TEXT PRIMARY KEY, case_id TEXT NOT NULL, ts TEXT NOT NULL, "
                "kind TEXT NOT NULL, summary TEXT NOT NULL, data TEXT NOT NULL)"
            )

    # ------------------------------------------------------------------ cases

    def save_case(self, case: Case) -> None:
        with self._conn() as con:
            con.execute(
                "INSERT OR REPLACE INTO iw_cases (id, data, updated_at) VALUES (?, ?, ?)",
                (case.id, case.model_dump_json(), utcnow().isoformat()),
            )

    def get_case(self, case_id: str) -> Case | None:
        with self._conn() as con:
            row = con.execute("SELECT data FROM iw_cases WHERE id = ?", (case_id,)).fetchone()
        return Case.model_validate_json(row["data"]) if row else None

    def list_cases(self) -> list[Case]:
        with self._conn() as con:
            rows = con.execute("SELECT data FROM iw_cases ORDER BY updated_at DESC").fetchall()
        return [Case.model_validate_json(r["data"]) for r in rows]

    def get_case_by_token(self, token: str) -> tuple[Case, Party] | None:
        """Magic-link resolution. Linear scan is fine at prototype scale."""
        for case in self.list_cases():
            for party in case.parties:
                if party.token == token:
                    return case, party
        return None

    # --------------------------------------------------------------- timeline

    def add_timeline(self, event: TimelineEvent) -> None:
        with self._conn() as con:
            con.execute(
                "INSERT INTO iw_timeline (id, case_id, ts, kind, summary, data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event.id, event.case_id, event.ts.isoformat(), event.kind,
                 event.summary, json.dumps(event.data)),
            )
        try:  # bridge mirror is optional and must never break the audit write
            from intake_workflow.integration import events_shim
            events_shim.on_timeline(event)
        except Exception:
            import logging
            logging.getLogger("intake_workflow.integration").exception("events_shim failed")

    def list_timeline(self, case_id: str) -> list[TimelineEvent]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM iw_timeline WHERE case_id = ? ORDER BY ts DESC", (case_id,)
            ).fetchall()
        return [
            TimelineEvent(
                id=r["id"], case_id=r["case_id"], ts=r["ts"], kind=r["kind"],
                summary=r["summary"], data=json.loads(r["data"]),
            )
            for r in rows
        ]
