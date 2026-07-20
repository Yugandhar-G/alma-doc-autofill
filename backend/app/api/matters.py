"""Matter API router — matters, documents, runs, and the interrupt inbox.

Every endpoint resolves a Principal (get_principal) and acts through the
TenantScope derived from it; the matter store filters every read/write by
scope.firm_id, so firm isolation is structural, not a per-handler check. Bodies
carry firm data by design; logs never do (PII rule — the store logs ids/counts
only, and this layer adds nothing to the wire log).

WorkflowService/Scheduler singleton: a single process-lifetime instance backs
the run endpoints. This is correct for the desktop model — the sidecar is one
process on one machine, so one Scheduler owns the concurrency gate and one
RunManager caches the compiled graphs. It is constructed lazily (first run
request) via the same factories the rest of the app uses, and exposed through
the get_workflow_service dependency so tests can override it with a temp-path
instance.
"""
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.kernel.auth import Principal, get_principal, scope_of
from app.kernel.ratelimit import rate_limit
from app.kernel.runtime.workflows import WorkflowError, WorkflowService
from app.kernel.store.base import MatterStore, TenantScope, get_matter_store
from app.packages.autofill.service import read_capped
from app.schemas import ApiResponse
from app.storage.base import get_store

logger = logging.getLogger("yunaki.api.matters")

router = APIRouter(prefix="/api")

# --- Workflow service singleton (desktop sidecar; see module docstring) -----
_service: WorkflowService | None = None


def _service_singleton() -> WorkflowService:
    global _service
    if _service is None:
        from app.registry import INSTALLED_PACKAGES

        _service = WorkflowService(get_matter_store(), INSTALLED_PACKAGES)
        logger.info("workflow service initialised")
    return _service


def get_workflow_service() -> WorkflowService:
    """FastAPI dependency for the run-lifecycle service. Overridable in tests
    (app.dependency_overrides) with an instance bound to temp paths."""
    return _service_singleton()


# --- Request bodies ---------------------------------------------------------
class CreateMatterRequest(BaseModel):
    matter_type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    client_ref: str | None = Field(None, max_length=200)


class StartRunRequest(BaseModel):
    package_id: str = Field(min_length=1, max_length=64)
    initial: dict = Field(default_factory=dict)


class ResumeRunRequest(BaseModel):
    payload: dict = Field(default_factory=dict)


# --- Helpers ----------------------------------------------------------------
def _error(message: str, status: int) -> JSONResponse:
    """A business-rule failure in the standard envelope, with an HTTP status."""
    return JSONResponse(
        status_code=status,
        content=ApiResponse(success=False, error=message).model_dump(),
    )


def _workflow_status(message: str) -> int:
    """Map a WorkflowError to an HTTP status by its (fixed, PII-free) message."""
    if "not found" in message or "unknown" in message:
        return 404
    if "awaiting" in message:
        return 409
    return 400


def _scope(principal: Principal) -> TenantScope:
    return scope_of(principal)


# --- Matters ----------------------------------------------------------------
@router.post("/matters", dependencies=[Depends(rate_limit("write"))])
async def create_matter(
    req: CreateMatterRequest,
    principal: Principal = Depends(get_principal),
    store: MatterStore = Depends(get_matter_store),
) -> ApiResponse:
    matter = await store.create_matter(
        _scope(principal), req.matter_type, req.title, client_ref=req.client_ref
    )
    return ApiResponse(success=True, data={"matter": matter.model_dump()})


@router.get("/matters")
async def list_matters(
    principal: Principal = Depends(get_principal),
    store: MatterStore = Depends(get_matter_store),
) -> ApiResponse:
    matters = await store.list_matters(_scope(principal))
    return ApiResponse(
        success=True, data={"matters": [m.model_dump() for m in matters]}
    )


@router.get("/matters/{matter_id}")
async def get_matter(
    matter_id: str,
    principal: Principal = Depends(get_principal),
    store: MatterStore = Depends(get_matter_store),
):
    scope = _scope(principal)
    matter = await store.get_matter(scope, matter_id)
    if matter is None:
        return _error("matter not found", 404)
    documents = await store.list_documents(scope, matter_id)
    runs = await store.list_runs(scope, matter_id=matter_id)
    return ApiResponse(
        success=True,
        data={
            "matter": matter.model_dump(),
            "documents": [d.model_dump() for d in documents],
            "runs": [r.model_dump() for r in runs],
        },
    )


@router.post(
    "/matters/{matter_id}/documents", dependencies=[Depends(rate_limit("write"))]
)
async def upload_documents(
    matter_id: str,
    files: list[UploadFile] = File(...),
    doc_type: str = Form("document"),
    principal: Principal = Depends(get_principal),
    store: MatterStore = Depends(get_matter_store),
):
    """Dumb upload: persist each blob via the DocumentStore and index it into
    the matter as a MatterDocument row. No extraction here — packages extract
    inside their runs. Oversized files (per the upload cap) are reported, never
    saved."""
    scope = _scope(principal)
    if await store.get_matter(scope, matter_id) is None:
        return _error("matter not found", 404)

    blobs = get_store()
    saved = []
    rejected: list[str] = []
    for upload in files:
        content = await read_capped(upload)
        if content is None:
            rejected.append(upload.filename or "unnamed")
            continue
        doc_id = await blobs.save_document(content, doc_type, upload.filename or "unnamed")
        row = await store.add_document(
            scope, matter_id, doc_id, doc_type, upload.filename or "unnamed"
        )
        saved.append(row.model_dump())
    logger.info(
        "matter documents uploaded matter_id=%s saved=%d rejected=%d",
        matter_id,
        len(saved),
        len(rejected),
    )
    return ApiResponse(
        success=True, data={"documents": saved, "rejected": rejected}
    )


@router.post("/matters/{matter_id}/runs", dependencies=[Depends(rate_limit("write"))])
async def start_run(
    matter_id: str,
    req: StartRunRequest,
    principal: Principal = Depends(get_principal),
    service: WorkflowService = Depends(get_workflow_service),
):
    """Validate `initial` through the package's own state model, then start the
    run. A malformed initial state is a 400 before any row is created."""
    scope = _scope(principal)
    try:
        package = service.package(req.package_id)
    except WorkflowError as exc:
        return _error(str(exc), _workflow_status(str(exc)))

    try:
        # run_id is a placeholder here; start_run re-stamps the authoritative
        # store-minted id onto the state before executing.
        initial_state = package.state_model(run_id=uuid.uuid4().hex, **req.initial)
    except (ValidationError, TypeError) as exc:
        logger.info("invalid initial state package=%s error=%s", req.package_id, type(exc).__name__)
        return _error("invalid initial state for package", 400)

    try:
        run = await service.start_run(scope, matter_id, req.package_id, initial_state)
    except WorkflowError as exc:
        return _error(str(exc), _workflow_status(str(exc)))
    return ApiResponse(success=True, data={"run": run.model_dump()})


# --- Runs -------------------------------------------------------------------
@router.get("/runs/{run_id}")
async def run_status(
    run_id: str,
    principal: Principal = Depends(get_principal),
    service: WorkflowService = Depends(get_workflow_service),
    store: MatterStore = Depends(get_matter_store),
):
    scope = _scope(principal)
    run = await service.run_status(scope, run_id)
    if run is None:
        return _error("run not found", 404)
    artifacts = await store.list_artifacts(scope, run_id)
    return ApiResponse(
        success=True,
        data={
            "run": run.model_dump(),
            "artifacts": [a.model_dump() for a in artifacts],
        },
    )


@router.post("/runs/{run_id}/resume", dependencies=[Depends(rate_limit("write"))])
async def resume_run(
    run_id: str,
    req: ResumeRunRequest,
    principal: Principal = Depends(get_principal),
    service: WorkflowService = Depends(get_workflow_service),
):
    scope = _scope(principal)
    try:
        report = await service.resume_run(scope, run_id, req.payload)
    except WorkflowError as exc:
        return _error(str(exc), _workflow_status(str(exc)))
    run = await service.run_status(scope, run_id)
    return ApiResponse(
        success=True,
        data={
            "run": run.model_dump() if run is not None else None,
            "report": report,
        },
    )


# --- Inbox ------------------------------------------------------------------
@router.get("/inbox")
async def inbox(
    principal: Principal = Depends(get_principal),
    service: WorkflowService = Depends(get_workflow_service),
) -> ApiResponse:
    """The firm's pending human-review checkpoints — every parked run awaiting
    an attorney/staff decision."""
    interrupts = await service.pending_interrupts(_scope(principal))
    return ApiResponse(
        success=True, data={"interrupts": [i.model_dump() for i in interrupts]}
    )
