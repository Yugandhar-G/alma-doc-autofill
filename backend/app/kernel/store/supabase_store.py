"""Supabase MatterStore — the firm-sync plane when SUPABASE_URL /
SUPABASE_SERVICE_KEY are set. Mirrors app.storage.supabase_store: the
supabase-py client is synchronous, so every call is pushed off the event loop
via asyncio.to_thread, and misconfigured credentials fail LOUD rather than
silently falling back to SQLite.

Tables are created by backend/supabase/migrations/0001_matters.sql. RLS is
enabled there; the backend uses the service-role key (RLS-exempt), so the
tenancy wall is enforced in THIS layer — every query filters by scope.firm_id,
exactly as the SQLite store does — until the E2 RLS policies are finalized.

This layer cannot be integration-tested offline; test_matter_store asserts
method-signature parity with the SQLite store so the two never drift.

PII rule: only ids and counts are logged.
"""
import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from supabase import Client, create_client

from app.kernel.config import Settings
from app.kernel.store.base import MatterStore, TenantScope, thread_id_for
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

logger = logging.getLogger("yunaki.kernel.store.supabase")

_FIRMS = "firms"
_USERS = "users"
_MATTERS = "matters"
_DOCUMENTS = "matter_documents"
_RUNS = "workflow_runs"
_ARTIFACTS = "run_artifacts"
_INTERRUPTS = "interrupts"
_MEMORY = "memory_records"


class SupabaseError(RuntimeError):
    """Raised when Supabase is configured but a matter-store operation fails."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _new_id() -> str:
    return uuid4().hex


class SupabaseMatterStore(MatterStore):
    def __init__(self, settings: Settings) -> None:
        if not (settings.supabase_url and settings.supabase_service_key):
            raise SupabaseError(
                "SupabaseMatterStore requires SUPABASE_URL and SUPABASE_SERVICE_KEY. "
                "Unset both to fall back to local SQLite (matter_store_path)."
            )
        try:
            self._client: Client = create_client(
                settings.supabase_url, settings.supabase_service_key
            )
        except Exception as exc:
            raise SupabaseError(
                "Could not initialize the Supabase client. Check SUPABASE_URL and "
                f"SUPABASE_SERVICE_KEY in backend/.env. Cause: {exc}"
            ) from exc

    # --- Low-level helpers (all off the event loop) ------------------------
    async def _insert(self, table: str, row: dict) -> None:
        def _op() -> None:
            self._client.table(table).insert(row).execute()

        try:
            await asyncio.to_thread(_op)
        except Exception as exc:
            raise SupabaseError(
                f"Supabase insert into {table!r} failed. Verify the table exists "
                "— see backend/supabase/migrations/0001_matters.sql. "
                f"Cause: {exc}"
            ) from exc

    async def _select(
        self, table: str, filters: list[tuple[str, str]], *, limit: int | None = None,
        order_desc: bool = False,
    ) -> list[dict]:
        def _op() -> list[dict]:
            query = self._client.table(table).select("*")
            for column, value in filters:
                query = query.eq(column, value)
            if order_desc:
                query = query.order("created_at", desc=True)
            if limit is not None:
                query = query.limit(limit)
            response = query.execute()
            return response.data or []

        try:
            return await asyncio.to_thread(_op)
        except Exception as exc:
            raise SupabaseError(
                f"Supabase read from {table!r} failed. Cause: {exc}"
            ) from exc

    async def _update(
        self, table: str, patch: dict, filters: list[tuple[str, str]]
    ) -> None:
        def _op() -> None:
            query = self._client.table(table).update(patch)
            for column, value in filters:
                query = query.eq(column, value)
            query.execute()

        try:
            await asyncio.to_thread(_op)
        except Exception as exc:
            raise SupabaseError(
                f"Supabase update on {table!r} failed. Cause: {exc}"
            ) from exc

    # --- Firm bootstrap ----------------------------------------------------
    async def create_firm(self, name: str) -> Firm:
        firm = Firm(id=_new_id(), name=name, created_at=_now())
        await self._insert(_FIRMS, {"id": firm.id, "name": name, "created_at": _iso(firm.created_at)})
        logger.info("created firm firm_id=%s", firm.id)
        return firm

    async def create_user(
        self,
        firm_id: str,
        email: str,
        role: UserRole,
        auth_provider_id: str | None = None,
    ) -> User:
        user = User(
            id=_new_id(), firm_id=firm_id, email=email, role=role,
            auth_provider_id=auth_provider_id, created_at=_now(),
        )
        await self._insert(_USERS, {
            "id": user.id, "firm_id": firm_id, "email": email, "role": role,
            "auth_provider_id": auth_provider_id, "created_at": _iso(user.created_at),
        })
        logger.info("created user user_id=%s firm_id=%s role=%s", user.id, firm_id, role)
        return user

    async def get_user_by_auth_id(self, auth_provider_id: str) -> User | None:
        rows = await self._select(_USERS, [("auth_provider_id", auth_provider_id)], limit=1)
        return None if not rows else User.model_validate(rows[0])

    # --- Matters -----------------------------------------------------------
    async def create_matter(
        self,
        scope: TenantScope,
        matter_type: str,
        title: str,
        client_ref: str | None = None,
    ) -> Matter:
        matter = Matter(
            id=_new_id(), firm_id=scope.firm_id, matter_type=matter_type, title=title,
            client_ref=client_ref, status="open", created_by=scope.user_id, created_at=_now(),
        )
        await self._insert(_MATTERS, {
            "id": matter.id, "firm_id": matter.firm_id, "matter_type": matter_type,
            "title": title, "client_ref": client_ref, "status": "open",
            "created_by": scope.user_id, "created_at": _iso(matter.created_at),
        })
        logger.info("created matter matter_id=%s firm_id=%s type=%s", matter.id, scope.firm_id, matter_type)
        return matter

    async def get_matter(self, scope: TenantScope, matter_id: str) -> Matter | None:
        rows = await self._select(
            _MATTERS, [("id", matter_id), ("firm_id", scope.firm_id)], limit=1
        )
        return None if not rows else Matter.model_validate(rows[0])

    async def list_matters(self, scope: TenantScope) -> list[Matter]:
        rows = await self._select(_MATTERS, [("firm_id", scope.firm_id)], order_desc=True)
        return [Matter.model_validate(row) for row in rows]

    async def _require_matter(self, scope: TenantScope, matter_id: str) -> None:
        if await self.get_matter(scope, matter_id) is None:
            raise ValueError(f"Matter {matter_id!r} not found in firm {scope.firm_id!r}")

    # --- Documents ---------------------------------------------------------
    async def add_document(
        self,
        scope: TenantScope,
        matter_id: str,
        doc_id: str,
        doc_type: str,
        filename: str,
    ) -> MatterDocument:
        await self._require_matter(scope, matter_id)
        doc = MatterDocument(
            id=_new_id(), matter_id=matter_id, firm_id=scope.firm_id, doc_id=doc_id,
            doc_type=doc_type, filename=filename, uploaded_by=scope.user_id, created_at=_now(),
        )
        await self._insert(_DOCUMENTS, {
            "id": doc.id, "matter_id": matter_id, "firm_id": scope.firm_id, "doc_id": doc_id,
            "doc_type": doc_type, "filename": filename, "uploaded_by": scope.user_id,
            "created_at": _iso(doc.created_at),
        })
        logger.info("added document doc_row=%s matter_id=%s doc_id=%s", doc.id, matter_id, doc_id)
        return doc

    async def list_documents(
        self, scope: TenantScope, matter_id: str
    ) -> list[MatterDocument]:
        rows = await self._select(
            _DOCUMENTS, [("matter_id", matter_id), ("firm_id", scope.firm_id)], order_desc=True
        )
        return [MatterDocument.model_validate(row) for row in rows]

    # --- Runs --------------------------------------------------------------
    async def create_run(
        self, scope: TenantScope, matter_id: str, package_id: str
    ) -> WorkflowRun:
        await self._require_matter(scope, matter_id)
        run_id = _new_id()
        run = WorkflowRun(
            id=run_id, matter_id=matter_id, firm_id=scope.firm_id, package_id=package_id,
            status="queued", thread_id=thread_id_for(scope.firm_id, matter_id, run_id),
            started_by=scope.user_id, created_at=_now(), finished_at=None, summary_json={},
        )
        await self._insert(_RUNS, {
            "id": run.id, "matter_id": matter_id, "firm_id": scope.firm_id, "package_id": package_id,
            "status": "queued", "thread_id": run.thread_id, "started_by": scope.user_id,
            "created_at": _iso(run.created_at), "finished_at": None, "summary_json": {},
        })
        logger.info("created run run_id=%s matter_id=%s package=%s", run.id, matter_id, package_id)
        return run

    async def get_run(self, scope: TenantScope, run_id: str) -> WorkflowRun | None:
        rows = await self._select(
            _RUNS, [("id", run_id), ("firm_id", scope.firm_id)], limit=1
        )
        return None if not rows else WorkflowRun.model_validate(rows[0])

    async def update_run_status(
        self,
        scope: TenantScope,
        run_id: str,
        status: RunStatus,
        summary_json: dict | None = None,
        finished_at_now: bool = False,
    ) -> WorkflowRun:
        existing = await self.get_run(scope, run_id)
        if existing is None:
            raise ValueError(f"Run {run_id!r} not found in firm {scope.firm_id!r}")
        patch: dict = {"status": status}
        patch["summary_json"] = {**existing.summary_json, **(summary_json or {})}
        if finished_at_now:
            patch["finished_at"] = _iso(_now())
        await self._update(_RUNS, patch, [("id", run_id), ("firm_id", scope.firm_id)])
        logger.info("run status run_id=%s status=%s", run_id, status)
        updated = await self.get_run(scope, run_id)
        if updated is None:
            raise SupabaseError(f"Run {run_id!r} vanished after update")
        return updated

    async def list_runs(
        self,
        scope: TenantScope,
        matter_id: str | None = None,
        status: RunStatus | None = None,
    ) -> list[WorkflowRun]:
        filters = [("firm_id", scope.firm_id)]
        if matter_id is not None:
            filters.append(("matter_id", matter_id))
        if status is not None:
            filters.append(("status", status))
        rows = await self._select(_RUNS, filters, order_desc=True)
        return [WorkflowRun.model_validate(row) for row in rows]

    async def _require_run(self, scope: TenantScope, run_id: str) -> None:
        if await self.get_run(scope, run_id) is None:
            raise ValueError(f"Run {run_id!r} not found in firm {scope.firm_id!r}")

    # --- Artifacts ---------------------------------------------------------
    async def add_artifact(
        self, scope: TenantScope, run_id: str, kind: ArtifactKind, artifact_ref: str
    ) -> RunArtifact:
        await self._require_run(scope, run_id)
        artifact = RunArtifact(
            id=_new_id(), run_id=run_id, firm_id=scope.firm_id, kind=kind,
            artifact_ref=artifact_ref, created_at=_now(),
        )
        await self._insert(_ARTIFACTS, {
            "id": artifact.id, "run_id": run_id, "firm_id": scope.firm_id, "kind": kind,
            "artifact_ref": artifact_ref, "created_at": _iso(artifact.created_at),
        })
        logger.info("added artifact artifact_id=%s run_id=%s kind=%s", artifact.id, run_id, kind)
        return artifact

    async def list_artifacts(
        self, scope: TenantScope, run_id: str
    ) -> list[RunArtifact]:
        rows = await self._select(
            _ARTIFACTS, [("run_id", run_id), ("firm_id", scope.firm_id)], order_desc=True
        )
        return [RunArtifact.model_validate(row) for row in rows]

    # --- Interrupts --------------------------------------------------------
    async def create_interrupt(
        self,
        scope: TenantScope,
        run_id: str,
        kind: str,
        node: str,
        payload_json: dict,
    ) -> Interrupt:
        await self._require_run(scope, run_id)
        interrupt = Interrupt(
            id=_new_id(), run_id=run_id, firm_id=scope.firm_id, kind=kind, node=node,
            payload_json=payload_json, status="pending", created_at=_now(),
            resolved_by=None, resolved_at=None,
        )
        await self._insert(_INTERRUPTS, {
            "id": interrupt.id, "run_id": run_id, "firm_id": scope.firm_id, "kind": kind,
            "node": node, "payload_json": payload_json, "status": "pending",
            "created_at": _iso(interrupt.created_at), "resolved_by": None, "resolved_at": None,
        })
        logger.info("created interrupt interrupt_id=%s run_id=%s node=%s", interrupt.id, run_id, node)
        return interrupt

    async def resolve_interrupt(
        self,
        scope: TenantScope,
        interrupt_id: str,
        resolved_by: str,
        status: str = "resolved",
    ) -> Interrupt:
        rows = await self._select(
            _INTERRUPTS, [("id", interrupt_id), ("firm_id", scope.firm_id)], limit=1
        )
        if not rows:
            raise ValueError(
                f"Interrupt {interrupt_id!r} not found in firm {scope.firm_id!r}"
            )
        await self._update(
            _INTERRUPTS,
            {"status": status, "resolved_by": resolved_by, "resolved_at": _iso(_now())},
            [("id", interrupt_id), ("firm_id", scope.firm_id)],
        )
        logger.info("resolved interrupt interrupt_id=%s status=%s", interrupt_id, status)
        updated = await self._select(
            _INTERRUPTS, [("id", interrupt_id), ("firm_id", scope.firm_id)], limit=1
        )
        if not updated:
            raise SupabaseError(f"Interrupt {interrupt_id!r} vanished after update")
        return Interrupt.model_validate(updated[0])

    async def list_interrupts(
        self, scope: TenantScope, status: str | None = None
    ) -> list[Interrupt]:
        filters = [("firm_id", scope.firm_id)]
        if status is not None:
            filters.append(("status", status))
        rows = await self._select(_INTERRUPTS, filters, order_desc=True)
        return [Interrupt.model_validate(row) for row in rows]

    # --- Memory ------------------------------------------------------------
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
        await self._require_matter(scope, matter_id)
        record = MemoryRecord(
            id=_new_id(), firm_id=scope.firm_id, matter_id=matter_id, run_id=run_id,
            matter_type=matter_type, kind=kind, criterion_key=criterion_key,
            summary=summary, detail_json=detail_json, created_at=_now(),
        )
        await self._insert(_MEMORY, {
            "id": record.id, "firm_id": scope.firm_id, "matter_id": matter_id, "run_id": run_id,
            "matter_type": matter_type, "kind": kind, "criterion_key": criterion_key,
            "summary": summary, "detail_json": detail_json, "created_at": _iso(record.created_at),
        })
        logger.info("added memory memory_id=%s matter_id=%s kind=%s", record.id, matter_id, kind)
        return record

    async def list_memories(
        self,
        scope: TenantScope,
        matter_type: str | None = None,
        criterion_key: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        filters = [("firm_id", scope.firm_id)]
        if matter_type is not None:
            filters.append(("matter_type", matter_type))
        if criterion_key is not None:
            filters.append(("criterion_key", criterion_key))
        rows = await self._select(_MEMORY, filters, limit=limit, order_desc=True)
        return [MemoryRecord.model_validate(row) for row in rows]
