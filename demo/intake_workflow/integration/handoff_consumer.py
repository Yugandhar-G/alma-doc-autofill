"""handoff_consumer — our Slack handoffs open cases in the intake app.

A background daemon thread polls the shared ``event`` table for
``case.handoff_received`` events. For each new one it reads our ``case`` /
``party`` / ``client`` rows, then calls the intake app's ``api.create_case`` to
open the local intake case, records the id mapping, and writes the freshly-minted
client portal links back into OUR ``intake`` rows.

Robustness:
  - Requires BOTH a petitioner and a beneficiary client, each with a non-empty
    email; otherwise it logs loudly and skips (records nothing — retryable).
  - One bad event never kills the loop: it is logged and skipped, and the
    high-water mark still advances past it.
  - The high-water mark lives in ``iw_bridge_state['handoff_high_water']`` so a
    restart does not reprocess old events.
"""
from __future__ import annotations

import logging
import threading
import time

_log = logging.getLogger("intake_workflow.integration.handoff_consumer")

HANDOFF_EVENT_TYPE = "case.handoff_received"
HIGH_WATER_KEY = "handoff_high_water"
POLL_INTERVAL_SECONDS = 2.0


class HandoffConsumer:
    """Daemon-thread poller. ``start(store)`` / ``stop()``; safe to stop twice."""

    def __init__(self, poll_interval: float = POLL_INTERVAL_SECONDS) -> None:
        self._poll_interval = poll_interval
        self._store = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ lifecycle

    def start(self, store) -> None:
        """Ensure aux tables exist, then spin up the daemon poll loop."""
        from intake_workflow.integration import config

        conn = config.shared_conn()
        try:
            config.ensure_tables(conn)
        finally:
            conn.close()

        self._store = store
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="iw-handoff-consumer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the loop to exit and join briefly. Idempotent."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._poll_interval * 2 + 1)
        self._thread = None

    # ------------------------------------------------------------------ poll loop

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:  # a poll failure must never kill the loop
                _log.exception("handoff_consumer: poll cycle failed")
            self._stop.wait(self._poll_interval)

    def poll_once(self) -> int:
        """Process all handoff events past the high-water mark. Returns count seen.

        Public for deterministic, network-free testing (drive it directly).
        """
        from intake_workflow.integration import config

        conn = config.shared_conn()
        try:
            config.ensure_tables(conn)
            high_water = self._read_high_water(conn)
            rows = conn.execute(
                "SELECT rowid, case_id FROM event "
                "WHERE type = ? AND rowid > ? ORDER BY rowid ASC",
                (HANDOFF_EVENT_TYPE, high_water),
            ).fetchall()

            for row in rows:
                try:
                    self._process_event(conn, row["case_id"])
                except Exception:  # one bad event never stalls the others
                    _log.exception(
                        "handoff_consumer: failed to process handoff for core "
                        "case %s", row["case_id"],
                    )
                finally:
                    # Advance the high-water mark regardless of per-event outcome.
                    self._write_high_water(conn, row["rowid"])
            return len(rows)
        finally:
            conn.close()

    # ------------------------------------------------------------------ internals

    def _process_event(self, conn, core_case_id: str | None) -> None:
        from intake_workflow.integration import config
        from intake_workflow.domain import api

        if core_case_id is None:
            _log.warning("handoff_consumer: handoff event with no case_id; skipping")
            return

        if config.yew_case_for(conn, core_case_id) is not None:
            return  # already opened locally

        case_row = conn.execute(
            'SELECT id, name FROM "case" WHERE id = ?', (core_case_id,)
        ).fetchone()
        if case_row is None:
            _log.warning(
                "handoff_consumer: no /core case row for %s; skipping", core_case_id
            )
            return

        parties = self._load_parties(conn, core_case_id)
        petitioner = parties.get("petitioner")
        beneficiary = parties.get("beneficiary")
        if not (petitioner and beneficiary):
            _log.warning(
                "handoff_consumer: core case %s missing a petitioner/beneficiary "
                "client with a usable email; skipping (retryable)", core_case_id
            )
            return

        local_case = api.create_case(
            self._store,
            title=case_row["name"],
            petitioner_name=petitioner["name"],
            petitioner_email=petitioner["email"],
            beneficiary_name=beneficiary["name"],
            beneficiary_email=beneficiary["email"],
        )
        config.map_case(conn, local_case.id, core_case_id)
        self._write_portal_links(conn, core_case_id, local_case)

    @staticmethod
    def _load_parties(conn, core_case_id: str) -> dict[str, dict]:
        """Return {role: {client_id, name, email}} for roles with a usable email."""
        rows = conn.execute(
            "SELECT p.role AS role, c.id AS client_id, c.first_name AS first_name, "
            "c.last_name AS last_name, c.email AS email "
            'FROM party p JOIN client c ON c.id = p.client_id '
            "WHERE p.case_id = ?",
            (core_case_id,),
        ).fetchall()
        out: dict[str, dict] = {}
        for row in rows:
            email = (row["email"] or "").strip()
            if not email:
                continue
            name = f"{row['first_name']} {row['last_name']}".strip()
            out[row["role"]] = {
                "client_id": row["client_id"],
                "name": name,
                "email": email,
            }
        return out

    def _write_portal_links(self, conn, core_case_id: str, local_case) -> None:
        """Point each of our intake rows at the matching local portal token."""
        from intake_workflow.integration import config
        from intake_workflow.schemas import PartyRole

        base = config.portal_base()
        token_by_role = {
            "petitioner": local_case.party(PartyRole.petitioner).token,
            "beneficiary": local_case.party(PartyRole.beneficiary).token,
        }
        role_by_client = {
            row["client_id"]: row["role"]
            for row in conn.execute(
                "SELECT client_id, role FROM party WHERE case_id = ?", (core_case_id,)
            ).fetchall()
        }
        intake_rows = conn.execute(
            "SELECT id, client_id FROM intake WHERE case_id = ?", (core_case_id,)
        ).fetchall()
        for row in intake_rows:
            role = role_by_client.get(row["client_id"])
            token = token_by_role.get(role)
            if token is None:
                continue
            conn.execute(
                "UPDATE intake SET url = ? WHERE id = ?",
                (f"{base}/c/{token}", row["id"]),
            )
        conn.commit()

    # ------------------------------------------------------------------ high-water

    @staticmethod
    def _read_high_water(conn) -> int:
        row = conn.execute(
            "SELECT value FROM iw_bridge_state WHERE key = ?", (HIGH_WATER_KEY,)
        ).fetchone()
        if row is None or row["value"] is None:
            return 0
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _write_high_water(conn, rowid: int) -> None:
        conn.execute(
            "INSERT INTO iw_bridge_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (HIGH_WATER_KEY, str(rowid)),
        )
        conn.commit()
