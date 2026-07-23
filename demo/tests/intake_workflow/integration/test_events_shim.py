"""events_shim: Nanda's audit trail surfaces (conservatively) on our bus."""
from __future__ import annotations

from datetime import datetime, timezone

from intake_workflow.schemas import TimelineEvent


def _timeline(kind: str, case_id: str, data: dict) -> TimelineEvent:
    return TimelineEvent(
        case_id=case_id,
        ts=datetime.now(timezone.utc),
        kind=kind,
        summary="audit line",
        data=data,
    )


def _map(core_conn, yew_case_id: str = "yew-1", core_case_id: str = "case_test"):
    from intake_workflow.integration import config

    config.map_case(core_conn, yew_case_id, core_case_id)
    return yew_case_id, core_case_id


def test_item_submitted_becomes_client_activity(bridge_env, core_conn, seed):
    info = seed()
    from intake_workflow.integration import events_shim
    from core.events import query_events

    yew_id, core_id = _map(core_conn, "yew-1", info["case_id"])
    events_shim.on_timeline(
        _timeline("item_submitted", yew_id,
                  {"item": "pet_bio", "state": "checked", "findings": []})
    )

    events = query_events(core_conn, case_id=core_id, type="intake.client_activity")
    assert len(events) == 1
    ev = events[0]
    assert ev.actor == "client"
    assert ev.payload == {"item": "pet_bio"}


def test_attorney_review_flagged_becomes_escalation(bridge_env, core_conn, seed):
    info = seed()
    from intake_workflow.integration import events_shim
    from core.events import query_events

    yew_id, core_id = _map(core_conn, "yew-1", info["case_id"])
    events_shim.on_timeline(
        _timeline("attorney_review_flagged", yew_id,
                  {"item": "ben_eligibility", "codes": ["criminal_history"]})
    )

    events = query_events(core_conn, case_id=core_id, type="escalation.raised")
    assert len(events) == 1
    ev = events[0]
    assert ev.actor == "agent:validation"
    assert ev.payload == {"source": "yew-red-flag", "item": "ben_eligibility"}


def test_payloads_are_pii_free(bridge_env, core_conn, seed):
    """Only item keys / counts / flags ride the bus — never names or values."""
    info = seed()
    from intake_workflow.integration import events_shim
    from core.events import query_events

    yew_id, core_id = _map(core_conn, "yew-1", info["case_id"])
    events_shim.on_timeline(
        _timeline("item_submitted", yew_id, {"item": "ben_bio"})
    )
    events_shim.on_timeline(
        _timeline("attorney_review_flagged", yew_id, {"item": "ben_eligibility"})
    )

    for ev in query_events(core_conn, case_id=core_id):
        for value in ev.payload.values():
            text = str(value)
            assert "@" not in text            # no emails
            assert "Ravi" not in text and "Mei" not in text  # no names
        # Payload keys are limited to the conservative allow-list.
        assert set(ev.payload).issubset({"source", "item", "role", "fields_present",
                                         "has_uscis_number", "has_case_status",
                                         "draft_id", "kind", "channel"})


def test_unmapped_kinds_and_cases_are_skipped(bridge_env, core_conn, seed):
    info = seed()
    from intake_workflow.integration import events_shim
    from core.events import query_events

    _map(core_conn, "yew-1", info["case_id"])

    # Unmapped kind: not mirrored at all.
    events_shim.on_timeline(_timeline("case_created", "yew-1", {}))
    # Mapped kind but unknown case: silently skipped.
    events_shim.on_timeline(_timeline("item_submitted", "yew-unknown", {"item": "x"}))

    assert query_events(core_conn, case_id=info["case_id"], type="intake.client_activity") == []
