"""Matter-store interface — Supabase when configured (firm-sync plane), local
SQLite otherwise. Two concrete implementations; keep the method set minimal.

The tenancy discipline (non-negotiable): every method except the three
firm-bootstrap ones takes a `TenantScope` as its first argument and filters by
`scope.firm_id` INSIDE the implementation. A router or service literally cannot
express a cross-firm read — there is no code path that fetches a row without
its firm_id being matched first. This is the structural wall Phase E2 audits;
it lives in the store, not in a caller's discipline.

Method-set rationale (why each exists — the C/D tiers need exactly this and no
more; anything speculative waits for a real caller):
- create_firm / create_user / get_user_by_auth_id — bootstrap a tenant and
  resolve the signed-in identity to a User (the only pre-scope operations).
- create_matter / get_matter / list_matters — the case-file CRUD every package
  opens against.
- add_document / list_documents — index existing DocumentStore blobs into a
  matter (no blob duplication).
- create_run / get_run / update_run_status / list_runs — the run lifecycle
  (queue → run → terminal) plus the two query shapes the UI needs: a matter's
  runs, and a firm's runs in a given status (the work queue).
- add_artifact / list_artifacts — durable run outputs, listed per run.
- create_interrupt / resolve_interrupt / list_interrupts — the HITL queue: a
  run raises one, a reviewer resolves it, the firm lists what's pending.
- add_memory / list_memories — firm memory (writers land in D1); listed by
  matter_type + criterion_key, newest first, bounded.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.kernel.store.models import (
    ArtifactKind,
    Firm,
    Interrupt,
    Matter,
    MatterDocument,
    MemoryKind,
    MemoryRecord,
    RunArtifact,
    RunStatus,
    User,
    UserRole,
    WorkflowRun,
)


@dataclass(frozen=True)
class TenantScope:
    """The firm + acting user every scoped call is filtered and attributed to.
    Frozen so a scope cannot be mutated mid-request to widen access."""

    firm_id: str
    user_id: str


def thread_id_for(firm_id: str, matter_id: str, run_id: str) -> str:
    """Checkpointer thread namespace. Firm-scoped from day one so two firms'
    runs can never collide on a shared checkpoint thread."""
    return f"{firm_id}:{matter_id}:{run_id}"


class MatterStore(ABC):
    # --- Firm bootstrap (the only pre-scope operations) --------------------
    @abstractmethod
    async def create_firm(self, name: str) -> Firm:
        """Create a tenant; returns it with a store-minted id."""

    @abstractmethod
    async def create_user(
        self,
        firm_id: str,
        email: str,
        role: UserRole,
        auth_provider_id: str | None = None,
    ) -> User:
        """Create a firm member. auth_provider_id links external identity."""

    @abstractmethod
    async def get_user_by_auth_id(self, auth_provider_id: str) -> User | None:
        """Resolve a signed-in identity to a User (or None if unknown)."""

    # --- Matters ------------------------------------------------------------
    @abstractmethod
    async def create_matter(
        self,
        scope: TenantScope,
        matter_type: str,
        title: str,
        client_ref: str | None = None,
    ) -> Matter:
        """Open a matter in the caller's firm (status='open', created_by=user)."""

    @abstractmethod
    async def get_matter(self, scope: TenantScope, matter_id: str) -> Matter | None:
        """Fetch a matter by id, scoped to the firm (None if not in-firm)."""

    @abstractmethod
    async def list_matters(self, scope: TenantScope) -> list[Matter]:
        """All matters in the caller's firm, newest first."""

    # --- Documents ----------------------------------------------------------
    @abstractmethod
    async def add_document(
        self,
        scope: TenantScope,
        matter_id: str,
        doc_id: str,
        doc_type: str,
        filename: str,
    ) -> MatterDocument:
        """Index an existing DocumentStore blob (by content-hash doc_id) into a
        matter. No blob duplication — this is a pointer row."""

    @abstractmethod
    async def list_documents(
        self, scope: TenantScope, matter_id: str
    ) -> list[MatterDocument]:
        """Documents attached to a matter, newest first."""

    # --- Runs ---------------------------------------------------------------
    @abstractmethod
    async def create_run(
        self, scope: TenantScope, matter_id: str, package_id: str
    ) -> WorkflowRun:
        """Queue a workflow run (status='queued'); mints the checkpointer
        thread_id via thread_id_for."""

    @abstractmethod
    async def get_run(self, scope: TenantScope, run_id: str) -> WorkflowRun | None:
        """Fetch a run by id, scoped to the firm."""

    @abstractmethod
    async def update_run_status(
        self,
        scope: TenantScope,
        run_id: str,
        status: RunStatus,
        summary_json: dict | None = None,
        finished_at_now: bool = False,
    ) -> WorkflowRun:
        """Transition a run's status; optionally merge summary_json and stamp
        finished_at (set finished_at_now on terminal transitions)."""

    @abstractmethod
    async def list_runs(
        self,
        scope: TenantScope,
        matter_id: str | None = None,
        status: RunStatus | None = None,
    ) -> list[WorkflowRun]:
        """Runs in the firm, filtered by matter and/or status (status alone =
        the firm-wide work queue), newest first."""

    # --- Artifacts ----------------------------------------------------------
    @abstractmethod
    async def add_artifact(
        self, scope: TenantScope, run_id: str, kind: ArtifactKind, artifact_ref: str
    ) -> RunArtifact:
        """Record a durable run output (pointer, not payload)."""

    @abstractmethod
    async def list_artifacts(
        self, scope: TenantScope, run_id: str
    ) -> list[RunArtifact]:
        """Artifacts produced by a run, newest first."""

    # --- Interrupts (HITL) --------------------------------------------------
    @abstractmethod
    async def create_interrupt(
        self,
        scope: TenantScope,
        run_id: str,
        kind: str,
        node: str,
        payload_json: dict,
    ) -> Interrupt:
        """Raise a human-review checkpoint (status='pending')."""

    @abstractmethod
    async def resolve_interrupt(
        self,
        scope: TenantScope,
        interrupt_id: str,
        resolved_by: str,
        status: str = "resolved",
    ) -> Interrupt:
        """Close an interrupt (status → resolved/expired), stamping who + when."""

    @abstractmethod
    async def list_interrupts(
        self, scope: TenantScope, status: str | None = None
    ) -> list[Interrupt]:
        """Interrupts in the firm, optionally filtered by status, newest first."""

    # --- Memory (writers land in D1) ---------------------------------------
    @abstractmethod
    async def add_memory(
        self,
        scope: TenantScope,
        matter_id: str,
        matter_type: str,
        kind: MemoryKind,
        summary: str,
        detail_json: dict,
        run_id: str | None = None,
        criterion_key: str | None = None,
    ) -> MemoryRecord:
        """Record a firm-memory entry (outcome/edit worth recalling)."""

    @abstractmethod
    async def list_memories(
        self,
        scope: TenantScope,
        matter_type: str | None = None,
        criterion_key: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        """Firm memory filtered by matter_type + criterion_key, newest first,
        bounded by limit."""


def get_matter_store() -> MatterStore:
    """Factory: SupabaseMatterStore when settings.supabase_enabled, else the
    local SQLite store. Mirrors app.storage.base.get_store()."""
    from app.kernel.config import get_settings

    settings = get_settings()
    if settings.supabase_enabled:
        from app.kernel.store.supabase_store import SupabaseMatterStore

        return SupabaseMatterStore(settings)
    from app.kernel.store.sqlite_store import SqliteMatterStore

    return SqliteMatterStore(settings)
