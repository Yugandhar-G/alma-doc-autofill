"""MemoryService — deterministic record/recall over the firm-scoped store, plus
the id-labeled prompt rendering the citation audit resolves against. Offline
(SQLite matter store on tmp_path); no LLM, no embeddings."""
from pathlib import Path

import pytest

from app.kernel.config import Settings
from app.kernel.memory.service import MemoryService
from app.kernel.store.base import TenantScope
from app.kernel.store.sqlite_store import SqliteMatterStore


@pytest.fixture
def store(tmp_path: Path) -> SqliteMatterStore:
    return SqliteMatterStore(
        Settings(_env_file=None, matter_store_path=str(tmp_path / "matters.db"))
    )


async def _bootstrap(store: SqliteMatterStore) -> tuple[TenantScope, TenantScope]:
    firm_a = await store.create_firm("Alpha LLP")
    firm_b = await store.create_firm("Beta PC")
    user_a = await store.create_user(firm_a.id, "a@alpha.test", "attorney", "auth-a")
    user_b = await store.create_user(firm_b.id, "b@beta.test", "staff", "auth-b")
    return (
        TenantScope(firm_id=firm_a.id, user_id=user_a.id),
        TenantScope(firm_id=firm_b.id, user_id=user_b.id),
    )


async def test_record_persists_and_recall_returns_it(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    memory = MemoryService(store)

    record = await memory.record(
        scope_a,
        matter_id=matter.id,
        run_id=None,
        matter_type="o1a",
        kind="rfe",
        summary="RFE on awards criterion",
        criterion_key="awards",
        detail={"paras": 3},
    )
    assert record.firm_id == scope_a.firm_id
    assert record.detail_json == {"paras": 3}

    recalled = await memory.recall(scope_a)
    assert [r.id for r in recalled] == [record.id]


async def test_record_defaults_detail_to_empty_dict(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    memory = MemoryService(store)
    record = await memory.record(
        scope_a, matter_id=matter.id, run_id=None, matter_type="o1a",
        kind="outcome_note", summary="note",
    )
    assert record.detail_json == {}


async def test_recall_filters_by_type_and_criterion(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    memory = MemoryService(store)
    await memory.record(scope_a, matter_id=matter.id, run_id=None, matter_type="o1a",
                        kind="rfe", summary="one", criterion_key="awards")
    await memory.record(scope_a, matter_id=matter.id, run_id=None, matter_type="o1a",
                        kind="denial", summary="two", criterion_key="press")
    await memory.record(scope_a, matter_id=matter.id, run_id=None, matter_type="eb1a",
                        kind="approval", summary="three", criterion_key="awards")

    o1a = await memory.recall(scope_a, matter_type="o1a")
    assert {r.summary for r in o1a} == {"one", "two"}

    awards = await memory.recall(scope_a, matter_type="o1a", criterion_key="awards")
    assert [r.summary for r in awards] == ["one"]


async def test_recall_is_newest_first_and_bounded(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    memory = MemoryService(store)
    for label in ("m1", "m2", "m3"):
        await memory.record(scope_a, matter_id=matter.id, run_id=None, matter_type="o1a",
                            kind="outcome_note", summary=label)
    limited = await memory.recall(scope_a, limit=2)
    assert [r.summary for r in limited] == ["m3", "m2"]


async def test_recall_is_firm_scoped_firm_b_sees_nothing_of_firm_a(store: SqliteMatterStore) -> None:
    """The tenancy wall lives in the store; MemoryService inherits it. Firm B
    recalls NONE of firm A's memory."""
    scope_a, scope_b = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    memory = MemoryService(store)
    await memory.record(scope_a, matter_id=matter.id, run_id=None, matter_type="o1a",
                        kind="rfe", summary="firm A secret")

    assert await memory.recall(scope_b) == []
    assert await memory.recall(scope_b, matter_type="o1a") == []
    # firm A still recalls its own
    assert len(await memory.recall(scope_a)) == 1


async def test_render_for_prompt_id_label_format(store: SqliteMatterStore) -> None:
    scope_a, _ = await _bootstrap(store)
    matter = await store.create_matter(scope_a, "o1a", "petition")
    memory = MemoryService(store)
    record = await memory.record(
        scope_a, matter_id=matter.id, run_id=None, matter_type="o1a",
        kind="rfe", summary="RFE on awards",
    )
    rendered = MemoryService.render_for_prompt([record])
    assert rendered == f"[memory:{record.id}] o1a/rfe RFE on awards"


async def test_render_for_prompt_empty_is_explicit() -> None:
    assert MemoryService.render_for_prompt([]) == "(no firm memory recalled)"
