"""Block-builder tests + WhatsApp mock approve path.

Feature 2: client_whatsapp drafts render an explicit "mocked this week" badge in
the approval post, and approving one still flows through sendgate's LIVE_MODE
gate — with no whatsapp sender registered, the no-op placeholder path runs and
the draft is marked sent(mocked) without any real send.
"""

from __future__ import annotations

import json

from core import drafts
from core.models import DraftAction, DraftGrounding, DraftTo
from slack_agent import blocks

from tests.slack_agent.conftest import approve_and_wait


# --------------------------------------------------------------------------- #
# Feature 2 — WhatsApp badge in the approval block
# --------------------------------------------------------------------------- #

def _draft(kind: str) -> DraftAction:
    return DraftAction(
        case_id="case_x",
        kind=kind,
        trigger="followup_timer",
        to=DraftTo(name="Ravi Kumar", channel_address="+1-555-0142"),
        subject=None,
        body="Hi Ravi, we still need a few documents.",
        grounding=DraftGrounding(missing_items=["W-2s"], days_since_activity=4),
    )


def test_whatsapp_draft_renders_badge():
    built = blocks.approval_blocks(_draft("client_whatsapp"))
    assert blocks.WHATSAPP_BADGE in json.dumps(built, ensure_ascii=False)
    # Badge sits before the body so the approver sees it up top.
    kinds = [b["type"] for b in built]
    assert kinds[:2] == ["section", "context"]


def test_email_draft_has_no_whatsapp_badge():
    built = blocks.approval_blocks(_draft("client_email"))
    assert blocks.WHATSAPP_BADGE not in json.dumps(built, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Feature 1 — completeness notification block content
# --------------------------------------------------------------------------- #

def test_intake_complete_blocks_carry_case_name_and_mention():
    built = blocks.intake_complete_blocks("Ravi Kumar / Mei Lin", "Isaiah")
    blob = json.dumps(built, ensure_ascii=False)
    assert "Intake complete — all mandatory items in" in blob
    assert "Ravi Kumar / Mei Lin" in blob
    assert "Isaiah" in blob


def test_intake_complete_blocks_use_supplied_handle():
    built = blocks.intake_complete_blocks("Ravi Kumar / Mei Lin", "@ops-desk")
    assert "@ops-desk" in json.dumps(built, ensure_ascii=False)


def test_validation_verdict_reports_auto_accept_and_attorney():
    built = blocks.validation_verdict_blocks(
        "Ravi Kumar / Mei Lin", "Isaiah",
        {"complete": True, "missing": [], "auto_accepted": 7, "attorney_review": 2},
    )
    blob = json.dumps(built, ensure_ascii=False)
    assert "Ready to file" in blob
    assert "auto-accepted 7 clean items" in blob
    assert "2 items still need attorney review" in blob
    assert "Ravi Kumar / Mei Lin" in blob
    assert "Isaiah" in blob


def test_validation_verdict_singular_and_no_attorney():
    built = blocks.validation_verdict_blocks(
        "A / B", "Isaiah",
        {"complete": True, "missing": [], "auto_accepted": 1, "attorney_review": 0},
    )
    blob = json.dumps(built, ensure_ascii=False)
    assert "auto-accepted 1 clean item" in blob and "1 clean items" not in blob
    assert "attorney review" not in blob


# --------------------------------------------------------------------------- #
# Feature 2 — approve a WhatsApp draft: no-op placeholder path, sent(mocked)
# --------------------------------------------------------------------------- #

def test_whatsapp_approve_runs_noop_path_and_marks_sent_mocked(db, slack, monkeypatch):
    # LIVE_MODE=false ⇒ sendgate mocks the send; no whatsapp sender is registered
    # so the resolved callable is the no-op placeholder (never invoked here).
    monkeypatch.setenv("LIVE_MODE", "false")
    draft = drafts.create_draft(db, _draft("client_whatsapp"))

    result = approve_and_wait(db, slack, draft.id, channel="C1", message_ts="7.0")

    assert result["mocked"] is True
    assert result["channel"] == "client_whatsapp"
    sent = drafts.get_draft(db, draft.id)
    assert sent.state == "sent"
