"""RFE-response package HTTP surface — the graph-backed RFE assembler path.

POST /runs             multipart notice upload + optional matter_id → the graph
                       extracts the notice (vision), parses grounds, checks the
                       deadline, distills + audits a checklist, and parks at
                       review_gate (checkpointed) → draft report + run_id
POST /runs/{id}/resume approved/edited checklist → Command(resume) → finalize →
                       final report (+ firm-memory write when a matter is attached)
GET  /runs/{id}        state peek (awaiting_review / done / unknown)

``today`` is stamped here at run start (the one place a wall-clock read is
allowed) and injected into graph state, so every node downstream is
deterministic and replayable. A run parked at review survives a restart:
existence is checked against the checkpointer, exactly like preflight.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from langgraph.types import Command
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.kernel.auth import Principal, get_principal, scope_of
from app.kernel.observability import request_trace
from app.kernel.runtime import RunManager, open_sqlite_checkpointer, thread_config
from app.kernel.store.base import MatterStore, get_matter_store
from app.packages.autofill.service import read_capped
from app.packages.rfe_response.graph import build_graph
from app.packages.rfe_response.schemas import (
    ResponseChecklist,
    RfeResponseReport,
    RfeResponseState,
)
from app.schemas import ApiResponse

logger = logging.getLogger("yunaki.rfe_response.api")

# Local checkpoint path (kernel config is owned elsewhere; a package-local
# default keeps the RFE runs off the other packages' DBs without touching it).
_CHECKPOINT_PATH = "uploads/rfe_response/checkpoints.db"

_RUNS = RunManager()


async def _build_rfe_graph():
    checkpointer = await open_sqlite_checkpointer(_CHECKPOINT_PATH)
    graph = build_graph(checkpointer=checkpointer)
    logger.info("rfe_response graph ready")
    return graph


async def _get_graph():
    return await _RUNS.get_or_build("rfe_response", _build_rfe_graph)


class ResumeRequest(BaseModel):
    """Approved/edited checklist. None → approve the draft unchanged. The
    checklist re-validates through the same ResponseChecklist schema."""

    checklist: ResponseChecklist | None = None


def _json_error(message: str) -> ApiResponse:
    return ApiResponse(success=False, error=message)


def _today() -> str:
    """UTC calendar date at run start — the single wall-clock read; every node
    consumes this value from state so runs stay replayable."""
    return datetime.now(timezone.utc).date().isoformat()


def _interrupt_report(result: dict) -> tuple[RfeResponseReport | None, list[str]]:
    """The draft report + audit warnings carried in the review interrupt."""
    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if not interrupts:
        return None, []
    value = interrupts[0].value or {}
    report = value.get("report")
    warnings = value.get("warnings") or []
    parsed = RfeResponseReport.model_validate(report) if report else None
    return parsed, warnings


def router_factory() -> APIRouter:
    router = APIRouter()

    @router.post("/runs")
    async def create_run(
        request: Request,
        notice: UploadFile | None = None,
        matter_id: str | None = Form(None),
        principal: Principal = Depends(get_principal),
        settings: Settings = Depends(get_settings),
        store: MatterStore = Depends(get_matter_store),
    ) -> ApiResponse:
        """Extract at the graph, run to review. A matter_id is optional — when
        present it is confirmed in-firm (a matter from another firm is a plain
        not-found), and it enables the checklist's matter-doc citations plus the
        finalize firm-memory write."""
        if notice is None:
            return _json_error("Upload an RFE notice.")
        content = await read_capped(notice)
        if content is None:
            return _json_error(f"File exceeds the {settings.max_file_mb} MB limit.")

        scope = scope_of(principal)
        confirmed_matter_id: str | None = None
        if matter_id:
            matter = await store.get_matter(scope, matter_id)
            if matter is None:
                return _json_error("Matter not found.")
            confirmed_matter_id = matter_id

        with request_trace("rfe_response.run", request.headers.get("x-session-id")) as trace:
            run_id = uuid.uuid4().hex
            graph = await _get_graph()
            state = RfeResponseState(
                run_id=run_id,
                firm_id=scope.firm_id,
                user_id=scope.user_id,
                matter_id=confirmed_matter_id,
                today=_today(),
                notice_bytes=content,
                notice_filename=notice.filename or "",
            )
            try:
                result = await graph.ainvoke(state, config=thread_config(run_id))
            except ValueError as exc:  # guardrail rejection — user-actionable
                return _json_error(str(exc))
            draft, warnings = _interrupt_report(result)
            if trace is not None:
                trace.update(
                    output={
                        "run_id": run_id,
                        "grounds": len(draft.notice.grounds) if draft else 0,
                        "items": len(draft.checklist.items) if draft else 0,
                    }
                )
            logger.info("rfe run parked at review run=%s", run_id)
            payload: dict = {"run_id": run_id, "warnings": warnings}
            if draft is not None:
                payload["report"] = draft.model_dump()
            return ApiResponse(success=True, data=payload)

    @router.post("/runs/{run_id}/resume")
    async def resume_run(run_id: str, req: ResumeRequest, request: Request) -> ApiResponse:
        """Resume with the human-approved checklist; edits re-validate through
        the same schema (ResumeRequest carries ResponseChecklist)."""
        graph = await _get_graph()
        config = thread_config(run_id)
        snapshot = await graph.aget_state(config)
        if snapshot is None or not snapshot.values:
            return _json_error("No run to resume.")
        if not snapshot.next:
            return _json_error("This run is not awaiting review.")
        with request_trace("rfe_response.resume", request.headers.get("x-session-id")):
            resume_value = {
                "checklist": req.checklist.model_dump() if req.checklist is not None else None
            }
            result = await graph.ainvoke(Command(resume=resume_value), config=config)
            report = result.get("report")
            if report is None:
                return _json_error("Run produced no report. Check server logs.")
            if not isinstance(report, RfeResponseReport):
                report = RfeResponseReport.model_validate(report)
            return ApiResponse(success=True, data=report.model_dump())

    @router.get("/runs/{run_id}")
    async def run_status(run_id: str) -> ApiResponse:
        graph = await _get_graph()
        snapshot = await graph.aget_state(thread_config(run_id))
        if snapshot is None or not snapshot.values:
            return _json_error("Unknown run.")
        status = "awaiting_review" if snapshot.next else "done"
        report = snapshot.values.get("report")
        data: dict = {"run_id": run_id, "status": status}
        if report is not None:
            if not isinstance(report, RfeResponseReport):
                report = RfeResponseReport.model_validate(report)
            data["report"] = report.model_dump()
        return ApiResponse(success=True, data=data)

    return router
