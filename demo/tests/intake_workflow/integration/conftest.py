"""Fixtures for the integration tests.

Fully offline: a tmp local intake Store, a tmp shared /core SQLite DB (created
via ``core.db.connect_and_init``), with ``DB_PATH`` monkeypatched so the native
integration's ``shared_conn()`` resolves to that same file, and
``YUNAKI_PORTAL_BASE`` monkeypatched for the portal deep links. FICTIONAL cast
only — no real PII ever enters the repo.

Merge note: the integration is native now — there is one database
(``core.config.get_db_path()``) and no opt-in ``YUNAKI_SHARED_DB`` env. The
shared /core DB and the local intake store point at the same monrepo DB file.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Core-side seed helper (direct SQL against our contract tables).
# --------------------------------------------------------------------------- #

def seed_core_case(
    conn,
    *,
    case_id: str = "case_test",
    name: str = "Ravi Kumar & Mei Lin",
    petitioner_email: str | None = "ravi.demo@example.com",
    beneficiary_email: str | None = "mei.demo@example.com",
    with_intakes: bool = True,
    with_stubs: bool = True,
    case_number: str | None = "YIL-2026-0001",
) -> dict:
    """Insert a fictional /core case: case + 2 clients + 2 parties (+ intakes,
    + history stubs). Returns the ids created so tests can assert against them.
    """
    pet_id = f"client_pet_{case_id}"
    ben_id = f"client_ben_{case_id}"
    now = _now()

    conn.execute(
        'INSERT INTO "case" (id, name, process_type, stage, created_at) '
        "VALUES (?, ?, ?, ?, ?)",
        (case_id, name, "marriage_aos", "opened", now),
    )
    conn.execute(
        "INSERT INTO client (id, first_name, last_name, email, phone, whatsapp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (pet_id, "Ravi", "Kumar", petitioner_email, "+1-555-0142", None),
    )
    conn.execute(
        "INSERT INTO client (id, first_name, last_name, email, phone, whatsapp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ben_id, "Mei", "Lin", beneficiary_email, None, None),
    )
    conn.execute(
        "INSERT INTO party (case_id, client_id, role) VALUES (?, ?, ?)",
        (case_id, pet_id, "petitioner"),
    )
    conn.execute(
        "INSERT INTO party (case_id, client_id, role) VALUES (?, ?, ?)",
        (case_id, ben_id, "beneficiary"),
    )

    pet_intake_id = f"intake_pet_{case_id}"
    ben_intake_id = f"intake_ben_{case_id}"
    if with_intakes:
        conn.execute(
            "INSERT INTO intake (id, case_id, client_id, url, state, sent_at, "
            "last_client_activity_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pet_intake_id, case_id, pet_id, "http://placeholder/pending", "sent",
             now, None),
        )
        conn.execute(
            "INSERT INTO intake (id, case_id, client_id, url, state, sent_at, "
            "last_client_activity_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ben_intake_id, case_id, ben_id, "http://placeholder/pending", "sent",
             now, None),
        )
    conn.commit()

    stub_ids: dict[str, str] = {}
    if with_stubs:
        from core import case_history

        pet_stub = case_history.create_stub(
            conn, case_id=case_id, role="petitioner",
            first_name="Ravi", last_name="Kumar", email=petitioner_email,
            case_number=case_number,
        )
        ben_stub = case_history.create_stub(
            conn, case_id=case_id, role="beneficiary",
            first_name="Mei", last_name="Lin", email=beneficiary_email,
            case_number=case_number,
        )
        stub_ids = {"petitioner": pet_stub.id, "beneficiary": ben_stub.id}

    return {
        "case_id": case_id,
        "name": name,
        "petitioner_client_id": pet_id,
        "beneficiary_client_id": ben_id,
        "petitioner_intake_id": pet_intake_id,
        "beneficiary_intake_id": ben_intake_id,
        "petitioner_email": petitioner_email,
        "beneficiary_email": beneficiary_email,
        "stub_ids": stub_ids,
        "case_number": case_number,
    }


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def shared_db_path(tmp_path) -> str:
    return str(tmp_path / "shared.db")


@pytest.fixture
def core_conn(shared_db_path):
    """A connection to a freshly-initialized shared /core DB."""
    from core.db import connect_and_init

    conn = connect_and_init(shared_db_path)
    yield conn
    conn.close()


@pytest.fixture
def bridge_env(shared_db_path, core_conn, monkeypatch):
    """Point the native integration at the tmp shared DB and create its aux tables.

    ``DB_PATH`` is the single monorepo DB the integration's ``shared_conn()``
    resolves via ``core.config.get_db_path()`` — it is set to the same file
    ``core_conn`` already initialized.
    """
    monkeypatch.setenv("DB_PATH", shared_db_path)
    monkeypatch.setenv("YUNAKI_PORTAL_BASE", "http://portal.test")

    from intake_workflow.integration import config

    conn = config.shared_conn()
    try:
        config.ensure_tables(conn)
    finally:
        conn.close()
    return shared_db_path


@pytest.fixture
def his_store(tmp_path):
    from intake_workflow.store import Store

    return Store(str(tmp_path / "his.db"))


@pytest.fixture
def seed(core_conn):
    """Return the seed helper bound to the shared connection."""
    def _seed(**kwargs):
        return seed_core_case(core_conn, **kwargs)

    return _seed


@pytest.fixture(autouse=True)
def _clear_event_subscribers():
    """Isolate the in-process pubsub between tests."""
    try:
        from core.events import clear_subscribers
    except Exception:
        yield
        return
    clear_subscribers()
    yield
    clear_subscribers()
