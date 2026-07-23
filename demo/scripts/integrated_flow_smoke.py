"""Live integrated-flow smoke — the monorepo intake workflow on one shared DB.

Boots the REAL intake-workflow FastAPI server (demo/intake_workflow, ported
from Nanda's Yunaki-Yew) against a throwaway DB and drives the whole firm
flow over HTTP:

  handoff (our casewrite) -> the HandoffConsumer opens the intake case +
  writes magic-link portal URLs into our intake.url -> client submits answers
  on the portal -> paralegal accepts in the staff UI -> integration layer
  upserts our typed case_history + mirrors events onto our bus -> follow-up
  drafted by the scheduler -> staff approve routes through SendgateProvider
  (the DEFAULT provider now) -> a PENDING DraftAction lands on our bus and
  NOTHING is sent (message_sent stays empty).

No Slack, no Gmail, no LLM calls — this proves the seams, not the models.
Run from demo/:  .venv/bin/python -m scripts.integrated_flow_smoke
Env: YEW_PORT (default 8791).

The one piece of test-harness time travel: the follow-up ladder needs days to
elapse, so we backdate created_at in the intake case blob before the scheduler
tick — throwaway DB only, to make "5 days later" happen in a smoke test.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from core.case_history import get_history
from core.db import connect_and_init
from core.events import emit, query_events
from core.models import Event
from slack_agent.casewrite import create_handoff_case
from slack_agent.handoff_agent import HandoffParse, HandoffParty

DEMO_DIR = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("YEW_PORT", "8791"))
BASE = f"http://127.0.0.1:{PORT}"

_checks: list[str] = []


def ok(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        print(f"  FAIL  {label}  {detail}")
        raise SystemExit(f"SMOKE FAILED at: {label}")
    _checks.append(label)
    print(f"  ok    {label}")


def wait_for(label: str, fn, timeout: float = 25.0, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    raise SystemExit(f"SMOKE FAILED waiting for: {label}")


def main() -> None:
    if not (DEMO_DIR / "intake_workflow").is_dir():
        raise SystemExit("demo/intake_workflow missing — the port hasn't landed.")
    tmp = Path(tempfile.mkdtemp(prefix="yunaki_flow_"))
    shared_db = tmp / "shared.db"
    print(f"[flow] workspace {tmp}")

    # ---- 1. our lane: handoff creates case + stubs + firm case number ----- #
    conn = connect_and_init(str(shared_db))
    conn.execute("PRAGMA journal_mode=WAL")
    handoff = create_handoff_case(
        conn,
        HandoffParse(
            process_type="I-130 and I-485 One Step Marriage Based Green Cards",
            parties=[
                HandoffParty("petitioner", "Ravi", "Kumar",
                             "ravi.kumar.demo@example.com", "+1-555-0142"),
                HandoffParty("beneficiary", "Mei", "Lin",
                             "mei.lin.demo@example.com", None),
            ],
        ),
    )
    case_id = handoff.case.id
    emit(conn, Event(type="case.handoff_received", case_id=case_id,
                     actor="agent:slack", payload={"parties": 2}))
    records = get_history(conn, case_id)
    case_number = records[0].case_number
    ok("handoff: 2 stubs, one firm case number",
       len(records) == 2 and bool(case_number) and case_number.startswith("YIL-")
       and all(r.case_number == case_number for r in records))

    # ---- 2. boot the real intake-workflow server (one shared DB) ---------- #
    env = {
        k: v for k, v in os.environ.items()
        if k not in ("YUNAKI_STAFF_PASSWORD", "YUNAKI_EMAIL_PROVIDER")
    }  # provider unset -> SendgateProvider is the native default
    env.update({
        "DB_PATH": str(shared_db),
        "YUNAKI_PORTAL_BASE": BASE,
        "YUNAKI_UPLOADS": str(tmp / "uploads"),
    })
    server = subprocess.Popen(
        [str(DEMO_DIR / ".venv" / "bin" / "python"), "-m", "uvicorn",
         "intake_workflow.main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=DEMO_DIR, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        client = httpx.Client(base_url=BASE, timeout=5.0)
        wait_for("his server", lambda: _up(client))
        ok("his app is up (bridge enabled)", True)

        # ---- 3. his consumer opens the case, links flow back to intake ---- #
        def _links():
            rows = conn.execute(
                "SELECT i.url, p.role FROM intake i "
                "JOIN party p ON p.client_id = i.client_id AND p.case_id = i.case_id "
                "WHERE i.case_id = ? AND i.url LIKE '%/c/%'", (case_id,),
            ).fetchall()
            return rows if len(rows) == 2 else None

        links = wait_for("consumer to write portal links", _links)
        tokens = {row["role"]: row["url"].rsplit("/c/", 1)[1] for row in links}
        yew_case_id = conn.execute(
            "SELECT yew_case_id FROM iw_case_map WHERE core_case_id = ?",
            (case_id,),
        ).fetchone()["yew_case_id"]
        ok("handoff consumed: intake case created + portal links in our intake.url",
           set(tokens) == {"petitioner", "beneficiary"})

        # ---- 4. client submits on HIS portal ------------------------------ #
        ben = tokens["beneficiary"]
        assert client.get(f"/c/{ben}").status_code == 200
        r1 = client.post(f"/c/{ben}/item/ben_bio/answers", data={
            "full_name": "Mei Lin", "dob": "1993-07-02",
            "a_number": "A123456789", "i94_number": "",
            "last_entry": "2024-08-19", "current_status": "F-1",
        })
        r2 = client.post(f"/c/{ben}/item/ben_eligibility/answers", data={
            "criminal_history": "No", "criminal_details": "",
            "immigration_violations": "No", "violation_details": "",
            "prior_denials": "Yes",
            "denial_details": "B-2 refused 2019 under 214(b)",
        })
        ok("client submitted two question sections on his portal",
           r1.status_code == 303 and r2.status_code == 303)

        # ---- 5. paralegal accepts in HIS staff UI -> our typed record ----- #
        for key in ("ben_bio", "ben_eligibility"):
            resp = client.post(
                f"/staff/case/{yew_case_id}/item/{key}/review",
                data={"action": "accepted", "reason": ""},
            )
            assert resp.status_code == 303, (key, resp.status_code)
        ben_rec = wait_for(
            "case_history upsert",
            lambda: next((r for r in get_history(conn, case_id, "beneficiary")
                          if r.beneficiary and r.beneficiary.a_number), None),
        )
        b = ben_rec.beneficiary
        ok("accepted answers landed in our typed case_history",
           b.legal_name.first == "Mei" and b.a_number == "A123456789"
           and b.immigration.current_status == "F-1"
           and b.immigration.visa_denied is True)
        ok("case number preserved through upsert",
           ben_rec.case_number == case_number)

        types = {e.type for e in query_events(conn, case_id=case_id)}
        ok("his activity mirrored onto our bus",
           "intake.client_activity" in types and "escalation.raised" in types,
           f"types={types}")

        # ---- 6. follow-up -> SendgateProvider -> pending draft, no send --- #
        _backdate_intake_case(shared_db, yew_case_id, days=5)
        assert client.post("/staff/tick").status_code == 303
        outreach_id = wait_for(
            "scheduler to draft a follow-up",
            lambda: _first_drafted_outreach(shared_db, yew_case_id),
        )
        assert client.post(
            f"/staff/case/{yew_case_id}/outreach/{outreach_id}/approve"
        ).status_code == 303

        draft = conn.execute("SELECT * FROM draft").fetchone()
        ok("his approve produced a PENDING draft on our bus",
           draft is not None and draft["state"] == "pending"
           and draft["kind"] == "client_email"
           and draft["to_channel_address"] == "ravi.kumar.demo@example.com")
        ok("draft.created emitted for our Slack approval card",
           any(e.type == "draft.created" for e in query_events(conn, case_id=case_id)))
        sent = conn.execute("SELECT COUNT(*) c FROM message_sent").fetchone()["c"]
        ok("NOTHING was actually sent (message_sent empty)", sent == 0)

    finally:
        server.terminate()
        server.wait(timeout=10)

    print(f"\nPASS — {len(_checks)} checks, full flow proven end to end.")
    print("handoff -> his case + portal links -> client submit -> staff accept "
          "-> typed case_history + bus events -> follow-up -> pending draft, zero sends")
    shutil.rmtree(tmp, ignore_errors=True)


def _up(client: httpx.Client) -> bool:
    try:
        return client.get("/staff").status_code == 200
    except httpx.HTTPError:
        return False


def _backdate_intake_case(db: Path, yew_case_id: str, *, days: int) -> None:
    """Test-harness time travel: make the ladder think the case is `days` old."""
    conn = sqlite3.connect(db)
    try:
        (blob,) = conn.execute(
            "SELECT data FROM iw_cases WHERE id = ?", (yew_case_id,)
        ).fetchone()
        data = json.loads(blob)
        past = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        data["created_at"] = past
        conn.execute("UPDATE iw_cases SET data = ? WHERE id = ?",
                     (json.dumps(data), yew_case_id))
        conn.commit()
    finally:
        conn.close()


def _first_drafted_outreach(db: Path, yew_case_id: str) -> str | None:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT data FROM iw_cases WHERE id = ?", (yew_case_id,)
        ).fetchone()
        if row is None:
            return None
        for event in json.loads(row[0]).get("outreach", []):
            if event.get("status") == "drafted":
                return event["id"]
        return None
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
