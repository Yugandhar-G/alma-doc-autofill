"""Shared offline helpers for the matter-intake agent tests (not collected —
no test_ prefix). Scripted model + fake doc store + firm bootstrap, mirroring
tests/test_screener_agent.py and tests/test_corpus_tools.py."""
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from app.kernel.config import Settings
from app.kernel.store.base import TenantScope
from app.kernel.store.sqlite_store import SqliteMatterStore
from app.schemas import ExtractionEnvelope


class ScriptedChatModel(FakeMessagesListChatModel):
    """Scripted turns for the deepagents loop; bind_tools is a no-op so the
    script alone decides what the 'model' calls."""

    def bind_tools(self, tools, **kwargs):
        return self


def tool_call_msg(*calls) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{i}"}
            for i, (name, args) in enumerate(calls)
        ],
    )


def scripted(*turns) -> ScriptedChatModel:
    return ScriptedChatModel(responses=list(turns))


class FakeDocStore:
    """Content-addressed extraction store keyed by (doc_id, doc_type, kind)."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str, str], ExtractionEnvelope] = {}

    def put(self, doc_id: str, doc_type: str, kind: str, detected: str) -> None:
        self._store[(doc_id, doc_type, kind)] = ExtractionEnvelope(
            document_type_requested=doc_type if doc_type in ("passport", "g28") else "passport",
            document_type_detected=detected,
            data={"x": 1},
        )

    async def get_extraction(self, doc_id: str, doc_type: str, kind: str = "raw"):
        return self._store.get((doc_id, doc_type, kind))


def make_store(tmp_path: Path) -> SqliteMatterStore:
    return SqliteMatterStore(
        Settings(_env_file=None, matter_store_path=str(tmp_path / "matters.db"))
    )


async def bootstrap(store: SqliteMatterStore) -> tuple[TenantScope, TenantScope]:
    firm_a = await store.create_firm("Alpha LLP")
    firm_b = await store.create_firm("Beta PC")
    user_a = await store.create_user(firm_a.id, "a@alpha.test", "attorney", "auth-a")
    user_b = await store.create_user(firm_b.id, "b@beta.test", "staff", "auth-b")
    return (
        TenantScope(firm_id=firm_a.id, user_id=user_a.id),
        TenantScope(firm_id=firm_b.id, user_id=user_b.id),
    )
