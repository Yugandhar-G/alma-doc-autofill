"""Local SQLite MatterStore — the zero-config firm-scoped data layer for
no-account / local-first mode. Backed by aiosqlite (its own worker thread, so
SQLite calls never block the event loop), WAL for concurrent reads during a
write, schema created idempotently on first connection.

Conventions mirrored from app.storage.local_store:
- content addressing lives upstream (doc_id is DocumentStore's hash); this
  store never sees blobs.
- JSON columns are TEXT via json.dumps/loads.
- Timestamps are timezone-aware UTC, stored as ISO-8601 strings.
- ids are uuid4 hex, minted here on create.

Tenancy wall: every scoped method filters by scope.firm_id in its WHERE clause
and stamps child rows' firm_id FROM the scope (never from the caller). Writes
that reference a parent (matter/run/interrupt) first verify the parent is
in-firm and fail loud otherwise — a cross-firm write is structurally
impossible, not merely discouraged.

PII rule: only ids and counts are logged, never titles, filenames, or
client_refs.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import aiosqlite

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

logger = logging.getLogger("yunaki.kernel.store.sqlite")

# Ordering tiebreaker: created_at can collide at microsecond resolution on fast
# successive inserts, so rowid (monotonic with insertion) makes "newest first"
# deterministic.
_NEWEST_FIRST = "ORDER BY created_at DESC, rowid DESC"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS firms (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id               TEXT PRIMARY KEY,
    firm_id          TEXT NOT NULL,
    email            TEXT NOT NULL,
    role             TEXT NOT NULL,
    auth_provider_id TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_firm ON users (firm_id);
CREATE INDEX IF NOT EXISTS idx_users_auth ON users (auth_provider_id);

CREATE TABLE IF NOT EXISTS matters (
    id          TEXT PRIMARY KEY,
    firm_id     TEXT NOT NULL,
    matter_type TEXT NOT NULL,
    title       TEXT NOT NULL,
    client_ref  TEXT,
    status      TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_matters_firm ON matters (firm_id);

CREATE TABLE IF NOT EXISTS matter_documents (
    id          TEXT PRIMARY KEY,
    matter_id   TEXT NOT NULL,
    firm_id     TEXT NOT NULL,
    doc_id      TEXT NOT NULL,
    doc_type    TEXT NOT NULL,
    filename    TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_matter ON matter_documents (matter_id);
CREATE INDEX IF NOT EXISTS idx_docs_firm ON matter_documents (firm_id);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id           TEXT PRIMARY KEY,
    matter_id    TEXT NOT NULL,
    firm_id      TEXT NOT NULL,
    package_id   TEXT NOT NULL,
    status       TEXT NOT NULL,
    thread_id    TEXT NOT NULL,
    started_by   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    finished_at  TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_runs_matter ON workflow_runs (matter_id);
CREATE INDEX IF NOT EXISTS idx_runs_firm ON workflow_runs (firm_id);
CREATE INDEX IF NOT EXISTS idx_runs_firm_status ON workflow_runs (firm_id, status);

CREATE TABLE IF NOT EXISTS run_artifacts (
    id           TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    firm_id      TEXT NOT NULL,
    kind         TEXT NOT NULL,
    artifact_ref TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON run_artifacts (run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_firm ON run_artifacts (firm_id);

CREATE TABLE IF NOT EXISTS interrupts (
    id           TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    firm_id      TEXT NOT NULL,
    kind         TEXT NOT NULL,
    node         TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    resolved_by  TEXT,
    resolved_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_interrupts_firm ON interrupts (firm_id);
CREATE INDEX IF NOT EXISTS idx_interrupts_firm_status ON interrupts (firm_id, status);

CREATE TABLE IF NOT EXISTS memory_records (
    id            TEXT PRIMARY KEY,
    firm_id       TEXT NOT NULL,
    matter_id     TEXT NOT NULL,
    run_id        TEXT,
    matter_type   TEXT NOT NULL,
    kind          TEXT NOT NULL,
    criterion_key TEXT,
    summary       TEXT NOT NULL,
    detail_json   TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_firm ON memory_records (firm_id);
CREATE INDEX IF NOT EXISTS idx_memory_matter ON memory_records (matter_id);
CREATE INDEX IF NOT EXISTS idx_memory_firm_type ON memory_records (firm_id, matter_type);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _new_id() -> str:
    return uuid4().hex


def _dt(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _json_loads(value: str | None) -> dict:
    return {} if value is None else json.loads(value)


class SqliteMatterStore(MatterStore):
    def __init__(self, settings: Settings) -> None:
        self._path = Path(settings.matter_store_path)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def _connection(self) -> aiosqlite.Connection:
        """Open (once, process-lifetime) the connection, enabling WAL and
        creating the schema idempotently. Guarded so concurrent first-callers
        don't race the CREATE TABLEs."""
        if self._conn is not None:
            return self._conn
        async with self._lock:
            if self._conn is not None:
                return self._conn
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(str(self._path))
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.executescript(_SCHEMA)
            await conn.commit()
            self._conn = conn
            logger.info("sqlite matter store ready path=%s", self._path)
            return self._conn

    async def _fetchone(self, sql: str, params: tuple) -> aiosqlite.Row | None:
        conn = await self._connection()
        async with conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def _fetchall(self, sql: str, params: tuple) -> list[aiosqlite.Row]:
        conn = await self._connection()
        async with conn.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

    async def _execute(self, sql: str, params: tuple) -> None:
        conn = await self._connection()
        await conn.execute(sql, params)
        await conn.commit()

    # --- Firm bootstrap ----------------------------------------------------
    async def create_firm(self, name: str) -> Firm:
        firm = Firm(id=_new_id(), name=name, created_at=_now())
        await self._execute(
            "INSERT INTO firms (id, name, created_at) VALUES (?, ?, ?)",
            (firm.id, firm.name, _iso(firm.created_at)),
        )
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
            id=_new_id(),
            firm_id=firm_id,
            email=email,
            role=role,
            auth_provider_id=auth_provider_id,
            created_at=_now(),
        )
        await self._execute(
            "INSERT INTO users (id, firm_id, email, role, auth_provider_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user.id, user.firm_id, user.email, user.role, user.auth_provider_id, _iso(user.created_at)),
        )
        logger.info("created user user_id=%s firm_id=%s role=%s", user.id, firm_id, role)
        return user

    async def get_user_by_auth_id(self, auth_provider_id: str) -> User | None:
        row = await self._fetchone(
            "SELECT * FROM users WHERE auth_provider_id = ?", (auth_provider_id,)
        )
        return None if row is None else _user(row)

    # --- Matters -----------------------------------------------------------
    async def create_matter(
        self,
        scope: TenantScope,
        matter_type: str,
        title: str,
        client_ref: str | None = None,
    ) -> Matter:
        matter = Matter(
            id=_new_id(),
            firm_id=scope.firm_id,
            matter_type=matter_type,
            title=title,
            client_ref=client_ref,
            status="open",
            created_by=scope.user_id,
            created_at=_now(),
        )
        await self._execute(
            "INSERT INTO matters (id, firm_id, matter_type, title, client_ref, status, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                matter.id, matter.firm_id, matter.matter_type, matter.title,
                matter.client_ref, matter.status, matter.created_by, _iso(matter.created_at),
            ),
        )
        logger.info("created matter matter_id=%s firm_id=%s type=%s", matter.id, scope.firm_id, matter_type)
        return matter

    async def get_matter(self, scope: TenantScope, matter_id: str) -> Matter | None:
        row = await self._fetchone(
            "SELECT * FROM matters WHERE id = ? AND firm_id = ?",
            (matter_id, scope.firm_id),
        )
        return None if row is None else _matter(row)

    async def list_matters(self, scope: TenantScope) -> list[Matter]:
        rows = await self._fetchall(
            f"SELECT * FROM matters WHERE firm_id = ? {_NEWEST_FIRST}",
            (scope.firm_id,),
        )
        return [_matter(row) for row in rows]

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
            id=_new_id(),
            matter_id=matter_id,
            firm_id=scope.firm_id,
            doc_id=doc_id,
            doc_type=doc_type,
            filename=filename,
            uploaded_by=scope.user_id,
            created_at=_now(),
        )
        await self._execute(
            "INSERT INTO matter_documents (id, matter_id, firm_id, doc_id, doc_type, filename, uploaded_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc.id, doc.matter_id, doc.firm_id, doc.doc_id, doc.doc_type,
                doc.filename, doc.uploaded_by, _iso(doc.created_at),
            ),
        )
        logger.info("added document doc_row=%s matter_id=%s doc_id=%s", doc.id, matter_id, doc_id)
        return doc

    async def list_documents(
        self, scope: TenantScope, matter_id: str
    ) -> list[MatterDocument]:
        rows = await self._fetchall(
            f"SELECT * FROM matter_documents WHERE matter_id = ? AND firm_id = ? {_NEWEST_FIRST}",
            (matter_id, scope.firm_id),
        )
        return [_document(row) for row in rows]

    # --- Runs --------------------------------------------------------------
    async def create_run(
        self, scope: TenantScope, matter_id: str, package_id: str
    ) -> WorkflowRun:
        await self._require_matter(scope, matter_id)
        run_id = _new_id()
        run = WorkflowRun(
            id=run_id,
            matter_id=matter_id,
            firm_id=scope.firm_id,
            package_id=package_id,
            status="queued",
            thread_id=thread_id_for(scope.firm_id, matter_id, run_id),
            started_by=scope.user_id,
            created_at=_now(),
            finished_at=None,
            summary_json={},
        )
        await self._execute(
            "INSERT INTO workflow_runs (id, matter_id, firm_id, package_id, status, thread_id, started_by, created_at, finished_at, summary_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.id, run.matter_id, run.firm_id, run.package_id, run.status,
                run.thread_id, run.started_by, _iso(run.created_at), None,
                json.dumps(run.summary_json),
            ),
        )
        logger.info("created run run_id=%s matter_id=%s package=%s", run.id, matter_id, package_id)
        return run

    async def get_run(self, scope: TenantScope, run_id: str) -> WorkflowRun | None:
        row = await self._fetchone(
            "SELECT * FROM workflow_runs WHERE id = ? AND firm_id = ?",
            (run_id, scope.firm_id),
        )
        return None if row is None else _run(row)

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
        merged = {**existing.summary_json, **(summary_json or {})}
        finished_at = _now() if finished_at_now else existing.finished_at
        await self._execute(
            "UPDATE workflow_runs SET status = ?, summary_json = ?, finished_at = ? "
            "WHERE id = ? AND firm_id = ?",
            (
                status, json.dumps(merged),
                _iso(finished_at) if finished_at else None,
                run_id, scope.firm_id,
            ),
        )
        logger.info("run status run_id=%s status=%s", run_id, status)
        updated = await self.get_run(scope, run_id)
        assert updated is not None  # just written under the same scope
        return updated

    async def list_runs(
        self,
        scope: TenantScope,
        matter_id: str | None = None,
        status: RunStatus | None = None,
    ) -> list[WorkflowRun]:
        clauses = ["firm_id = ?"]
        params: list = [scope.firm_id]
        if matter_id is not None:
            clauses.append("matter_id = ?")
            params.append(matter_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        rows = await self._fetchall(
            f"SELECT * FROM workflow_runs WHERE {' AND '.join(clauses)} {_NEWEST_FIRST}",
            tuple(params),
        )
        return [_run(row) for row in rows]

    async def _require_run(self, scope: TenantScope, run_id: str) -> None:
        if await self.get_run(scope, run_id) is None:
            raise ValueError(f"Run {run_id!r} not found in firm {scope.firm_id!r}")

    # --- Artifacts ---------------------------------------------------------
    async def add_artifact(
        self, scope: TenantScope, run_id: str, kind: ArtifactKind, artifact_ref: str
    ) -> RunArtifact:
        await self._require_run(scope, run_id)
        artifact = RunArtifact(
            id=_new_id(),
            run_id=run_id,
            firm_id=scope.firm_id,
            kind=kind,
            artifact_ref=artifact_ref,
            created_at=_now(),
        )
        await self._execute(
            "INSERT INTO run_artifacts (id, run_id, firm_id, kind, artifact_ref, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (artifact.id, artifact.run_id, artifact.firm_id, artifact.kind, artifact.artifact_ref, _iso(artifact.created_at)),
        )
        logger.info("added artifact artifact_id=%s run_id=%s kind=%s", artifact.id, run_id, kind)
        return artifact

    async def list_artifacts(
        self, scope: TenantScope, run_id: str
    ) -> list[RunArtifact]:
        rows = await self._fetchall(
            f"SELECT * FROM run_artifacts WHERE run_id = ? AND firm_id = ? {_NEWEST_FIRST}",
            (run_id, scope.firm_id),
        )
        return [_artifact(row) for row in rows]

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
            id=_new_id(),
            run_id=run_id,
            firm_id=scope.firm_id,
            kind=kind,
            node=node,
            payload_json=payload_json,
            status="pending",
            created_at=_now(),
            resolved_by=None,
            resolved_at=None,
        )
        await self._execute(
            "INSERT INTO interrupts (id, run_id, firm_id, kind, node, payload_json, status, created_at, resolved_by, resolved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                interrupt.id, interrupt.run_id, interrupt.firm_id, interrupt.kind,
                interrupt.node, json.dumps(interrupt.payload_json), interrupt.status,
                _iso(interrupt.created_at), None, None,
            ),
        )
        logger.info("created interrupt interrupt_id=%s run_id=%s node=%s", interrupt.id, run_id, node)
        return interrupt

    async def resolve_interrupt(
        self,
        scope: TenantScope,
        interrupt_id: str,
        resolved_by: str,
        status: str = "resolved",
    ) -> Interrupt:
        row = await self._fetchone(
            "SELECT * FROM interrupts WHERE id = ? AND firm_id = ?",
            (interrupt_id, scope.firm_id),
        )
        if row is None:
            raise ValueError(
                f"Interrupt {interrupt_id!r} not found in firm {scope.firm_id!r}"
            )
        resolved_at = _now()
        await self._execute(
            "UPDATE interrupts SET status = ?, resolved_by = ?, resolved_at = ? "
            "WHERE id = ? AND firm_id = ?",
            (status, resolved_by, _iso(resolved_at), interrupt_id, scope.firm_id),
        )
        logger.info("resolved interrupt interrupt_id=%s status=%s", interrupt_id, status)
        updated = await self._fetchone(
            "SELECT * FROM interrupts WHERE id = ? AND firm_id = ?",
            (interrupt_id, scope.firm_id),
        )
        assert updated is not None
        return _interrupt(updated)

    async def list_interrupts(
        self, scope: TenantScope, status: str | None = None
    ) -> list[Interrupt]:
        if status is None:
            rows = await self._fetchall(
                f"SELECT * FROM interrupts WHERE firm_id = ? {_NEWEST_FIRST}",
                (scope.firm_id,),
            )
        else:
            rows = await self._fetchall(
                f"SELECT * FROM interrupts WHERE firm_id = ? AND status = ? {_NEWEST_FIRST}",
                (scope.firm_id, status),
            )
        return [_interrupt(row) for row in rows]

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
            id=_new_id(),
            firm_id=scope.firm_id,
            matter_id=matter_id,
            run_id=run_id,
            matter_type=matter_type,
            kind=kind,
            criterion_key=criterion_key,
            summary=summary,
            detail_json=detail_json,
            created_at=_now(),
        )
        await self._execute(
            "INSERT INTO memory_records (id, firm_id, matter_id, run_id, matter_type, kind, criterion_key, summary, detail_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id, record.firm_id, record.matter_id, record.run_id,
                record.matter_type, record.kind, record.criterion_key,
                record.summary, json.dumps(record.detail_json), _iso(record.created_at),
            ),
        )
        logger.info("added memory memory_id=%s matter_id=%s kind=%s", record.id, matter_id, kind)
        return record

    async def list_memories(
        self,
        scope: TenantScope,
        matter_type: str | None = None,
        criterion_key: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        clauses = ["firm_id = ?"]
        params: list = [scope.firm_id]
        if matter_type is not None:
            clauses.append("matter_type = ?")
            params.append(matter_type)
        if criterion_key is not None:
            clauses.append("criterion_key = ?")
            params.append(criterion_key)
        params.append(limit)
        rows = await self._fetchall(
            f"SELECT * FROM memory_records WHERE {' AND '.join(clauses)} {_NEWEST_FIRST} LIMIT ?",
            tuple(params),
        )
        return [_memory(row) for row in rows]


# --- Row → model builders --------------------------------------------------
def _user(row: aiosqlite.Row) -> User:
    return User(
        id=row["id"],
        firm_id=row["firm_id"],
        email=row["email"],
        role=row["role"],
        auth_provider_id=row["auth_provider_id"],
        created_at=_dt(row["created_at"]),
    )


def _matter(row: aiosqlite.Row) -> Matter:
    return Matter(
        id=row["id"],
        firm_id=row["firm_id"],
        matter_type=row["matter_type"],
        title=row["title"],
        client_ref=row["client_ref"],
        status=row["status"],
        created_by=row["created_by"],
        created_at=_dt(row["created_at"]),
    )


def _document(row: aiosqlite.Row) -> MatterDocument:
    return MatterDocument(
        id=row["id"],
        matter_id=row["matter_id"],
        firm_id=row["firm_id"],
        doc_id=row["doc_id"],
        doc_type=row["doc_type"],
        filename=row["filename"],
        uploaded_by=row["uploaded_by"],
        created_at=_dt(row["created_at"]),
    )


def _run(row: aiosqlite.Row) -> WorkflowRun:
    return WorkflowRun(
        id=row["id"],
        matter_id=row["matter_id"],
        firm_id=row["firm_id"],
        package_id=row["package_id"],
        status=row["status"],
        thread_id=row["thread_id"],
        started_by=row["started_by"],
        created_at=_dt(row["created_at"]),
        finished_at=_dt(row["finished_at"]),
        summary_json=_json_loads(row["summary_json"]),
    )


def _artifact(row: aiosqlite.Row) -> RunArtifact:
    return RunArtifact(
        id=row["id"],
        run_id=row["run_id"],
        firm_id=row["firm_id"],
        kind=row["kind"],
        artifact_ref=row["artifact_ref"],
        created_at=_dt(row["created_at"]),
    )


def _interrupt(row: aiosqlite.Row) -> Interrupt:
    return Interrupt(
        id=row["id"],
        run_id=row["run_id"],
        firm_id=row["firm_id"],
        kind=row["kind"],
        node=row["node"],
        payload_json=_json_loads(row["payload_json"]),
        status=row["status"],
        created_at=_dt(row["created_at"]),
        resolved_by=row["resolved_by"],
        resolved_at=_dt(row["resolved_at"]),
    )


def _memory(row: aiosqlite.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        firm_id=row["firm_id"],
        matter_id=row["matter_id"],
        run_id=row["run_id"],
        matter_type=row["matter_type"],
        kind=row["kind"],
        criterion_key=row["criterion_key"],
        summary=row["summary"],
        detail_json=_json_loads(row["detail_json"]),
        created_at=_dt(row["created_at"]),
    )
