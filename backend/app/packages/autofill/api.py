"""Autofill package HTTP surface — the graph-backed run path.

POST /runs            multipart uploads → extract at the boundary → the graph
                      parks at review_gate (checkpointed) → JSON envelopes
POST /runs/{id}/resume reviewed data → Command(resume) → populate → report
GET  /runs/{id}       state peek (awaiting_review / done / unknown)

A run parked at review survives a backend restart: existence is checked
against the checkpointer, exactly like the screener's review endpoint.
"""
import logging
import uuid

from fastapi import APIRouter, Request, UploadFile
from langgraph.types import Command
from pydantic import BaseModel

from app.config import get_settings
from app.kernel.observability import request_trace
from app.kernel.runtime import RunManager, open_sqlite_checkpointer, thread_config
from app.packages.autofill.graph import build_graph
from app.packages.autofill.service import extract_slots
from app.packages.autofill.state import AutofillState
from app.schemas import ApiResponse, G28Data, PassportData, PopulationReport

logger = logging.getLogger("yunaki.autofill.api")

_RUNS = RunManager()


async def _build_autofill_graph():
    checkpointer = await open_sqlite_checkpointer(get_settings().autofill_checkpoint_path)
    graph = build_graph(checkpointer=checkpointer)
    logger.info("autofill graph ready")
    return graph


async def _get_graph():
    return await _RUNS.get_or_build("autofill", _build_autofill_graph)


class ResumeRequest(BaseModel):
    passport: PassportData | None = None
    g28: G28Data | None = None
    headed: bool | None = None


def _json_error(message: str) -> ApiResponse:
    return ApiResponse(success=False, error=message)


def router_factory() -> APIRouter:
    router = APIRouter()

    @router.post("/runs")
    async def create_run(
        request: Request,
        passport_front: UploadFile | None = None,
        passport_back: UploadFile | None = None,
        g28: UploadFile | None = None,
    ) -> ApiResponse:
        """Extract, then park the graph at review. Slot errors come back per
        slot exactly like the legacy /api/extract; a run is only created when
        at least one slot extracted."""
        if passport_front is None and g28 is None:
            return _json_error("Upload at least a passport front or a G-28.")
        with request_trace(
            "autofill.run", request.headers.get("x-session-id")
        ) as trace:
            data = await extract_slots(passport_front, passport_back, g28)
            passport_env = data.get("passport")
            g28_env = data.get("g28")
            usable = {
                key: env
                for key, env in (("passport", passport_env), ("g28", g28_env))
                if isinstance(env, dict) and "error" not in env
            }
            if not usable:
                return ApiResponse(success=False, error="No document extracted.", data=data)

            run_id = uuid.uuid4().hex
            graph = await _get_graph()
            state = AutofillState(
                run_id=run_id,
                passport_envelope=usable.get("passport"),
                g28_envelope=usable.get("g28"),
            )
            # Runs to the review interrupt and checkpoints there.
            await graph.ainvoke(state, config=thread_config(run_id))
            if trace is not None:
                trace.update(output={"run_id": run_id, "slots": sorted(usable)})
            logger.info("autofill run parked at review run=%s", run_id)
            return ApiResponse(success=True, data={"run_id": run_id, **data})

    @router.post("/runs/{run_id}/resume")
    async def resume_run(run_id: str, req: ResumeRequest, request: Request) -> ApiResponse:
        """Resume with the human-reviewed data; edited values re-validate
        through the same schemas (ResumeRequest is those schemas)."""
        graph = await _get_graph()
        config = thread_config(run_id)
        snapshot = await graph.aget_state(config)
        if snapshot is None or not snapshot.values:
            return _json_error("No run to resume.")
        if not snapshot.next:
            return _json_error("This run is not awaiting review.")
        with request_trace("autofill.resume", request.headers.get("x-session-id")):
            resume_value = {
                "passport": req.passport.model_dump() if req.passport else None,
                "g28": req.g28.model_dump() if req.g28 else None,
                "headed": req.headed,
            }
            result = await graph.ainvoke(Command(resume=resume_value), config=config)
            report = result.get("report")
            if report is None:
                return _json_error("Population produced no report. Check server logs.")
            if not isinstance(report, PopulationReport):
                report = PopulationReport.model_validate(report)
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
            if not isinstance(report, PopulationReport):
                report = PopulationReport.model_validate(report)
            data["report"] = report.model_dump()
        return ApiResponse(success=True, data=data)

    return router
