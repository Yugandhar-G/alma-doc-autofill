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


def test_no_usable_email_skipped_but_high_water_advances(
    bridge_env, his_store, core_conn, seed
):
    """Only when NEITHER side has a usable email is there nothing to act on."""
    from intake_workflow.integration import config

    info = seed(
        case_id="case_no_email",
        name="No Email Case",
        petitioner_email=None,
        beneficiary_email=None,   # neither party has a usable email
    )
    _emit_handoff(core_conn, info["case_id"])

    consumer = _consumer(his_store)
    assert consumer.poll_once() == 1        # event was seen
    assert his_store.list_cases() == []      # but nothing was created
    assert config.yew_case_for(core_conn, info["case_id"]) is None
    # High-water advanced: the skipped event is not reprocessed.
    assert consumer.poll_once() == 0


def _seed_one_party_core_case(conn, *, case_id: str, name: str) -> dict:
    """A genuine SINGLE-party /core case — exactly what the Slack create_case
    tool produces for '@yunaki create a case for <one person>': one client, one
    party, one intake, one history stub. (The shared seed helper always makes
    two parties, which is the couple case.)"""
    from datetime import datetime, timezone

    from core import case_history

    now = datetime.now(timezone.utc).isoformat()
    client_id = f"client_solo_{case_id}"
    intake_id = f"intake_solo_{case_id}"
    email = "yugandhar.demo@example.com"

    conn.execute(
        'INSERT INTO "case" (id, name, process_type, stage, created_at) '
        "VALUES (?, ?, ?, ?, ?)",
        (case_id, name, "", "Handoff received", now),
    )
    conn.execute(
        "INSERT INTO client (id, first_name, last_name, email, phone, whatsapp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (client_id, "Yugandhar", "Gopu", email, "+1-555-0100", None),
    )
    conn.execute(
        "INSERT INTO party (case_id, client_id, role) VALUES (?, ?, ?)",
        (case_id, client_id, "petitioner"),
    )
    conn.execute(
        "INSERT INTO intake (id, case_id, client_id, url, state, sent_at, "
        "last_client_activity_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (intake_id, case_id, client_id, "http://placeholder/pending", "sent", now, None),
    )
    conn.commit()
    case_history.create_stub(
        conn, case_id=case_id, role="petitioner", first_name="Yugandhar",
        last_name="Gopu", email=email, case_number="YIL-2026-0009",
    )
    return {"case_id": case_id, "intake_id": intake_id, "email": email}


def test_single_party_creates_case_with_placeholder_side(
    bridge_env, his_store, core_conn
):
    """A one-party handoff still opens a local case: the missing side is an
    explicit 'To be added' placeholder, and the portal link is written back for
    the real party (the only party/intake on our side)."""
    from intake_workflow.integration import config
    from intake_workflow.schemas import PartyRole

    info = _seed_one_party_core_case(
        core_conn, case_id="case_one_party", name="Solo Petitioner Case"
    )
    _emit_handoff(core_conn, info["case_id"])

    assert _consumer(his_store).poll_once() == 1

    cases = his_store.list_cases()
    assert len(cases) == 1
    local = cases[0]
    # Petitioner carried through; beneficiary is the explicit placeholder.
    pet = local.party(PartyRole.petitioner)
    ben = local.party(PartyRole.beneficiary)
    assert pet.email == info["email"]
    assert ben.full_name == "To be added" and ben.email == ""

    # Portal link written for the real petitioner intake (our only party).
    pet_url = core_conn.execute(
        "SELECT url FROM intake WHERE id = ?", (info["intake_id"],)
    ).fetchone()["url"]
    assert pet_url == f"http://portal.test/c/{pet.token}"

    assert config.yew_case_for(core_conn, info["case_id"]) == local.id
