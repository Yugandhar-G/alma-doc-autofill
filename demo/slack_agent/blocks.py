"""Block Kit builders — pure functions, no I/O, so they're trivially testable.

Action ids are the contract between these blocks and the handlers wired in
main.py:
  draft_approve / draft_edit / draft_reject   — approval buttons (value=draft_id)
  escal_send_again / escal_call_client / escal_pause — escalation quick actions
  draft_edit_submit / draft_reject_submit     — modal callback_ids
"""

from __future__ import annotations

import json
from typing import Any

from core.models import DraftAction

# --------------------------------------------------------------------------- #
# Trigger line
# --------------------------------------------------------------------------- #

def trigger_line(draft: DraftAction) -> str:
    """Human trigger summary from draft.trigger + grounding.days_since_activity."""
    days = draft.grounding.days_since_activity
    if draft.trigger == "followup_timer":
        if days:
            unit = "day" if days == 1 else "days"
            return f"Intake untouched {days} {unit}"
        return "Follow-up due"
    if draft.trigger == "validation_incomplete":
        return "Intake incomplete — documents still needed"
    if draft.trigger == "escalation":
        return "Escalation follow-up"
    return "Manual follow-up"


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"• {item}" for item in items)


# --------------------------------------------------------------------------- #
# Handoff summary
# --------------------------------------------------------------------------- #

def handoff_summary_blocks(
    case_name: str,
    process_type: str,
    captured_lines: list[str],
    missing: list[str],
) -> list[dict[str, Any]]:
    """What was captured from a handoff + explicit asks for every null field."""
    header = f"*Case handoff captured — {case_name}*"
    proc = process_type if process_type else "_not captured_"
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Process type:* {proc}"},
        },
    ]
    if captured_lines:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Captured:*\n" + _bullet_list(captured_lines),
                },
            }
        )
    if missing:
        asks = [f"missing: {item} — reply with it" for item in missing]
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Still needed (nothing was guessed):*\n"
                    + _bullet_list(asks),
                },
            }
        )
    return blocks


def ask_questions_blocks(questions: list[str]) -> list[dict[str, Any]]:
    """Reply when the agent asks in-thread instead of creating a case.

    Renders the agent's OWN questions verbatim when it supplied any; otherwise
    (a no-terminal/budget fallback) posts the generic ask. Never invents fields.
    """
    if not questions:
        return ask_for_fields_blocks(True)
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "I couldn't open a case from that message without guessing. "
                    "Reply with:\n" + _bullet_list(questions)
                ),
            },
        }
    ]


def ask_for_fields_blocks(parsing_available: bool) -> list[dict[str, Any]]:
    """Reply when nothing could be parsed. Never invents fields."""
    if parsing_available:
        text = (
            "I couldn't confidently pull the case details out of that message. "
            "Reply with the process type and each party's name, email, and phone "
            "and I'll open the case."
        )
    else:
        text = (
            "Automated parsing is unavailable right now (no ANTHROPIC_API_KEY). "
            "Reply with the process type and each party's name, email, and phone "
            "and I'll open the case manually."
        )
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


# --------------------------------------------------------------------------- #
# Approval
# --------------------------------------------------------------------------- #

def approval_blocks(draft: DraftAction) -> list[dict[str, Any]]:
    """Draft body + grounding + [Approve] [Edit] [Reject]."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{trigger_line(draft)}*"},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": draft.body}},
    ]
    if draft.grounding.missing_items:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Missing items:*\n"
                    + _bullet_list(draft.grounding.missing_items),
                },
            }
        )
    blocks.append(
        {
            "type": "actions",
            "block_id": "draft_actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "draft_approve",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "value": draft.id,
                },
                {
                    "type": "button",
                    "action_id": "draft_edit",
                    "text": {"type": "plain_text", "text": "Edit"},
                    "value": draft.id,
                },
                {
                    "type": "button",
                    "action_id": "draft_reject",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "value": draft.id,
                },
            ],
        }
    )
    return blocks


def _status_blocks(draft: DraftAction, status_line: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{trigger_line(draft)}*"},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": draft.body}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": status_line}]},
    ]


def approved_blocks(draft: DraftAction) -> list[dict[str, Any]]:
    return _status_blocks(
        draft, "✅ Approved — sent (mocked, LIVE_MODE=false)"
    )


def rejected_blocks(draft: DraftAction, reason: str | None) -> list[dict[str, Any]]:
    tail = f" — {reason}" if reason else ""
    return _status_blocks(draft, f"🚫 Rejected{tail}")


def approval_error_blocks(status_line: str) -> list[dict[str, Any]]:
    """Visible failure surface for the async approval task (§2.8).

    A background send failure must never be silent: the task logs loudly AND
    updates the Slack message with this block. status_line must carry no PII —
    the caller passes an error class name, not raw exception text.
    """
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*⚠️ Approval failed*"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": status_line}]},
    ]


# --------------------------------------------------------------------------- #
# Escalation
# --------------------------------------------------------------------------- #

def escalation_blocks(case_id: str, case_name: str) -> list[dict[str, Any]]:
    """Surface a B-raised escalation with demo-grade quick actions.

    Attorney is named in plain text ("Alison") — no real Slack user id is ever
    hardcoded (§2.4).
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Escalation — {case_name}*\n"
                    "Alison, the client hasn't touched the intake after 2 "
                    "reminders — what do you want to do?"
                ),
            },
        },
        {
            "type": "actions",
            "block_id": "escalation_actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "escal_send_again",
                    "text": {"type": "plain_text", "text": "Send again"},
                    "style": "primary",
                    "value": case_id,
                },
                {
                    "type": "button",
                    "action_id": "escal_call_client",
                    "text": {"type": "plain_text", "text": "Call client — assign task"},
                    "value": case_id,
                },
                {
                    "type": "button",
                    "action_id": "escal_pause",
                    "text": {"type": "plain_text", "text": "Pause chasing"},
                    "value": case_id,
                },
            ],
        },
    ]


def escalation_resolved_blocks(case_name: str, status_line: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Escalation — {case_name}*"},
        },
        {"type": "context", "elements": [{"type": "mrkdwn", "text": status_line}]},
    ]


# --------------------------------------------------------------------------- #
# Modals
# --------------------------------------------------------------------------- #

def edit_modal_view(draft: DraftAction, private_metadata: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": "draft_edit_submit",
        "private_metadata": json.dumps(private_metadata),
        "title": {"type": "plain_text", "text": "Edit draft"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "edit_body",
                "label": {"type": "plain_text", "text": "Message body"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "body",
                    "multiline": True,
                    "initial_value": draft.body,
                },
            }
        ],
    }


def reject_modal_view(private_metadata: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": "draft_reject_submit",
        "private_metadata": json.dumps(private_metadata),
        "title": {"type": "plain_text", "text": "Reject draft"},
        "submit": {"type": "plain_text", "text": "Reject"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "reject_reason",
                "optional": True,
                "label": {"type": "plain_text", "text": "Reason (optional)"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "reason",
                    "multiline": True,
                },
            }
        ],
    }
