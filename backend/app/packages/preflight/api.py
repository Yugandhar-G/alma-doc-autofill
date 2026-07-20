"""Preflight package HTTP surface — the graph-backed pre-filing audit path.

POST /runs             multipart uploads + case_type → extract at the boundary
                       (reusing the autofill slot pipeline) → the graph runs the
                       deterministic battery and parks at review_gate
                       (checkpointed) → draft report + run_id
POST /runs/{id}/resume approved/edited findings → Command(resume) → finalize →
                       final report
GET  /runs/{id}        state peek (awaiting_review / done / unknown)

A run parked at review survives a backend restart: existence is checked against
the checkpointer, exactly like autofill and the screener.
"""
import logging
import uuid

from fastapi import APIRouter, Form, Request, UploadFile
from langgraph.types import Command
from pydantic import BaseModel

from app.config import get_settings
from app.kernel.observability import request_trace
from app.kernel.runtime import RunManager, open_sqlite_checkpointer, thread_config
from app.packages.autofill.service import extract_slots
from app.packages.preflight.graph import build_graph
from app.packages.preflight.schemas import PreflightFinding, PreflightReport
from app.packages.preflight.state import PreflightState
from app.schemas import ApiResponse, ExtractionEnvelope

logger = logging.getLogger("yunaki.preflight.api")

_RUNS = RunManager()


async def _build_preflight_graph():
    checkpointer = await open_sqlite_checkpointer(get_settings().preflight_checkpoint_path)
    graph = build_graph(checkpointer=checkpointer)
    logger.info("preflight graph ready")
    return graph


async def _get_graph():
    return await _RUNS.get_or_build("preflight", _build_preflight_graph)


class ResumeRequest(BaseModel):
    """Approved/edited findings. None → approve the draft unchanged. Each entry
    re-validates through the same PreflightFinding schema the battery emits."""

    findings: list[PreflightFinding] | None = None


def _json_error(message: str) -> ApiResponse:
    return ApiResponse(success=False, error=message)


def _envelopes_from_slots(data: dict) -> list[ExtractionEnvelope]:
    """The usable extraction envelopes from the slot pipeline output — dumps
    that are dicts and carry no per-slot error become the packet."""
    envelopes: list[ExtractionEnvelope] = []
    for key in ("passport", "g28"):
        env = data.get(key)
        if isinstance(env, dict) and "error" not in env:
            envelopes.append(ExtractionEnvelope.model_validate(env))
    return envelopes


def router_factory() -> APIRouter:
    router = APIRouter()

    @router.post("/runs")
    async def create_run(
        request: Request,
        passport_front: UploadFile | None = None,
        passport_back: UploadFile | None = None,
        g28: UploadFile | None = None,
        case_type: str = Form("g28_filing"),
    ) -> ApiResponse:
        """Extract at the boundary, run the battery, park at review. Slot errors
        come back per slot exactly like autofill; a run is only created when at
        least one document extracted."""
        if passport_front is None and g28 is None:
            return _json_error("Upload at least a passport front or a G-28.")
        with request_trace("preflight.run", request.headers.get("x-session-id")) as trace:
            data = await extract_slots(passport_front, passport_back, g28)
            envelopes = _envelopes_from_slots(data)
            if not envelopes:
                return ApiResponse(success=False, error="No document extracted.", data=data)

            run_id = uuid.uuid4().hex
            graph = await _get_graph()
            state = PreflightState(
                run_id=run_id,
                case_type=case_type,
                envelopes=envelopes,
            )
            # Runs through the battery to the review interrupt, checkpoints there.
            result = await graph.ainvoke(state, config=thread_config(run_id))
            draft = _interrupt_report(result)
            if trace is not None:
                trace.update(
                    output={
                        "run_id": run_id,
                        "docs": len(envelopes),
                        "findings": len(draft.findings) if draft else 0,
                    }
                )
            logger.info("preflight run parked at review run=%s", run_id)
            payload: dict = {"run_id": run_id, **data}
            if draft is not None:
                payload["report"] = draft.model_dump()
            return ApiResponse(success=True, data=payload)

    @router.post("/runs/{run_id}/resume")
    async def resume_run(run_id: str, req: ResumeRequest, request: Request) -> ApiResponse:
        """Resume with the human-approved findings; edits re-validate through
        the same schema (ResumeRequest carries PreflightFinding)."""
        graph = await _get_graph()
        config = thread_config(run_id)
        snapshot = await graph.aget_state(config)
        if snapshot is None or not snapshot.values:
            return _json_error("No run to resume.")
        if not snapshot.next:
            return _json_error("This run is not awaiting review.")
        with request_trace("preflight.resume", request.headers.get("x-session-id")):
            resume_value = {
                "findings": [f.model_dump() for f in req.findings]
                if req.findings is not None
                else None
            }
            result = await graph.ainvoke(Command(resume=resume_value), config=config)
            report = result.get("report")
            if report is None:
                return _json_error("Audit produced no report. Check server logs.")
            if not isinstance(report, PreflightReport):
                report = PreflightReport.model_validate(report)
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
            if not isinstance(report, PreflightReport):
                report = PreflightReport.model_validate(report)
            data["report"] = report.model_dump()
        return ApiResponse(success=True, data=data)

    return router


def _interrupt_report(result: dict) -> PreflightReport | None:
    """The draft report carried in the review interrupt payload (or None)."""
    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if not interrupts:
        return None
    value = interrupts[0].value or {}
    report = value.get("report")
    return PreflightReport.model_validate(report) if report else None
