"""MemoryService — firm memory record + recall, over the matter store.

Design (v1, deterministic on purpose):
- record() writes one MemoryRecord through the firm-scoped store; recall()
  reads back by matter_type + criterion_key, newest first, bounded. There is
  NO semantic ranking yet — retrieval is deterministic filters + recency, which
  is auditable and cheap, and is the honest baseline a firm can trust.
- Firm scoping is not this service's job to enforce: every call takes a
  TenantScope and the store filters by scope.firm_id INSIDE the query, so
  firm B can never recall firm A's rows through here.
- render_for_prompt() emits id-labeled snippets so a model's output can cite a
  memory by id; the citation audit (screener/citations.py, kind=memory) then
  checks the cited id against the DETERMINISTIC set actually recalled and shown.

pgvector seam (later): a semantic recall path would embed `query` and rank
records by cosine similarity, then blend with recency. It would live as an
alternate recall_* method here, behind the same TenantScope + limit contract,
so callers (and the citable-source audit) do not change. Not built in v1 — no
real caller needs semantic recall yet, and a deterministic baseline is the
thing to beat before adding embeddings.
"""
from app.kernel.store.base import MatterStore, TenantScope
from app.kernel.store.models import MemoryKind, MemoryRecord

# Deterministic default recall breadth — small enough to stay inside a prompt
# budget, large enough that recency alone surfaces the relevant firm history.
_DEFAULT_RECALL_LIMIT = 10


class MemoryService:
    """Firm memory over a MatterStore. Stateless besides the store handle;
    every method is firm-scoped by its TenantScope argument."""

    def __init__(self, store: MatterStore) -> None:
        self._store = store

    async def record(
        self,
        scope: TenantScope,
        *,
        matter_id: str,
        run_id: str | None,
        matter_type: str,
        kind: MemoryKind,
        summary: str,
        criterion_key: str | None = None,
        detail: dict | None = None,
    ) -> MemoryRecord:
        """Persist one firm-memory entry (an outcome or edit worth recalling).
        Attributed and scoped to `scope`; detail defaults to an empty dict."""
        return await self._store.add_memory(
            scope,
            matter_id,
            matter_type,
            kind,
            summary,
            detail or {},
            run_id=run_id,
            criterion_key=criterion_key,
        )

    async def recall(
        self,
        scope: TenantScope,
        *,
        matter_type: str | None = None,
        criterion_key: str | None = None,
        limit: int = _DEFAULT_RECALL_LIMIT,
    ) -> list[MemoryRecord]:
        """Firm memory filtered by matter_type + criterion_key, newest first,
        bounded by limit. Deterministic — no embeddings (see module seam)."""
        return await self._store.list_memories(
            scope,
            matter_type=matter_type,
            criterion_key=criterion_key,
            limit=limit,
        )

    @staticmethod
    def render_for_prompt(records: list[MemoryRecord]) -> str:
        """Id-labeled snippets so model output can cite a memory by id:

            [memory:<id>] <matter_type>/<kind> <summary>

        The id label is exactly what a kind=memory SourceRef.ref must carry;
        the citation audit resolves it against the recalled set."""
        if not records:
            return "(no firm memory recalled)"
        return "\n".join(
            f"[memory:{r.id}] {r.matter_type}/{r.kind} {r.summary}" for r in records
        )
