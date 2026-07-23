"""handoff_consumer: our Slack handoffs open cases in Nanda's system."""
from __future__ import annotations

from intake_workflow.schemas import PartyRole


def _emit_handoff(core_conn, core_case_id: str) -> None:
    from core.events import emit
    from core.models import Event

    emit(
        core_conn,
        Event(type="case.handoff_received", case_id=core_case_id, actor="agent:slack"),
    )


def _consumer(his_store):
    from intake_workflow.integration.handoff_consumer import HandoffConsumer

    c = HandoffConsumer()
    c._store = his_store  # drive poll_once() directly, no thread
    return c


def test_handoff_creates_local_case_and_writes_portal_links(
    bridge_env, his_store, core_conn, seed
):
    from intake_workflow.integration import config

    info = seed()
    _emit_handoff(core_conn, info["case_id"])

    seen = _consumer(his_store).poll_once()
    assert seen == 1

    # His case exists with both parties and our case name as title.
    cases = his_store.list_cases()
    assert len(cases) == 1
    local = cases[0]
    assert local.title == info["name"]
    roles = {p.role for p in local.parties}
    assert roles == {PartyRole.petitioner, PartyRole.beneficiary}

    # Mapping row written.
    assert config.yew_case_for(core_conn, info["case_id"]) == local.id
    assert config.core_case_for(core_conn, local.id) == info["case_id"]

    # Our intake rows now point at the local portal tokens.
    pet_token = local.party(PartyRole.petitioner).token
    ben_token = local.party(PartyRole.beneficiary).token
    pet_url = core_conn.execute(
        "SELECT url FROM intake WHERE id = ?", (info["petitioner_intake_id"],)
    ).fetchone()["url"]
    ben_url = core_conn.execute(
        "SELECT url FROM intake WHERE id = ?", (info["beneficiary_intake_id"],)
    ).fetchone()["url"]
    assert pet_url == f"http://portal.test/c/{pet_token}"
    assert ben_url == f"http://portal.test/c/{ben_token}"


def test_high_water_prevents_reprocessing(bridge_env, his_store, core_conn, seed):
    info = seed()
    _emit_handoff(core_conn, info["case_id"])

    consumer = _consumer(his_store)
    assert consumer.poll_once() == 1
    # Second poll sees nothing new; no duplicate local case.
    assert consumer.poll_once() == 0
    assert len(his_store.list_cases()) == 1


def test_missing_email_skipped_but_high_water_advances(
    bridge_env, his_store, core_conn, seed
):
    from intake_workflow.integration import config

    info = seed(
        case_id="case_no_email",
        name="No Email Case",
        beneficiary_email=None,   # beneficiary has no usable email
    )
    _emit_handoff(core_conn, info["case_id"])

    consumer = _consumer(his_store)
    assert consumer.poll_once() == 1        # event was seen
    assert his_store.list_cases() == []      # but nothing was created
    assert config.yew_case_for(core_conn, info["case_id"]) is None
    # High-water advanced: the skipped event is not reprocessed.
    assert consumer.poll_once() == 0
