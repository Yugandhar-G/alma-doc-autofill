"""events_shim — the intake app's audit trail surfaces on our shared event bus.

Called from ONE choke point: the end of ``Store.add_timeline``. Only two of the
intake app's timeline kinds are mirrored (conservative by design):

  item_submitted          -> our Event(type='intake.client_activity', actor='client')
  attorney_review_flagged -> our Event(type='escalation.raised',
                                        actor='agent:validation',
                                        payload={'source': 'yew-red-flag'})

PII discipline (§4.4): mirrored payloads carry NO names/emails/answer values —
item keys and counts only. Timeline events for cases we don't have a mapping for
(the intake app's standalone cases) are silently skipped.
"""
from __future__ import annotations

import logging

_log = logging.getLogger("intake_workflow.integration.events_shim")

# The intake app's timeline kind -> (our event type, actor, extra PII-free payload).
_MIRRORED = {
    "item_submitted": ("intake.client_activity", "client", {}),
    "attorney_review_flagged": (
        "escalation.raised",
        "agent:validation",
        {"source": "yew-red-flag"},
    ),
}


def on_timeline(event) -> None:
    """Mirror a mapped TimelineEvent onto our bus. No-ops when unmapped."""
    from intake_workflow.integration import config

    if not config.enabled():
        return

    mapping = _MIRRORED.get(event.kind)
    if mapping is None:
        return
    event_type, actor, extra = mapping

    from core.events import emit
    from core.models import Event

    conn = config.shared_conn()
    try:
        core_case_id = config.core_case_for(conn, event.case_id)
        if core_case_id is None:
            return  # the intake app's standalone case; not ours to mirror

        # PII-free payload: the item key (a stable identifier, never a value)
        # plus any conservative extra flags declared in _MIRRORED.
        payload = dict(extra)
        item_key = event.data.get("item") if isinstance(event.data, dict) else None
        if item_key is not None:
            payload["item"] = item_key

        emit(
            conn,
            Event(
                type=event_type,
                case_id=core_case_id,
                actor=actor,
                payload=payload,
            ),
        )
    finally:
        conn.close()
