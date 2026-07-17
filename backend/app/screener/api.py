"""Screener HTTP surface. Same conventions as main.py: ApiResponse envelope,
request_trace grouping by X-Session-Id, PII-safe logging (session ids, hashes
and counts only — intake answers and report content go in response bodies and
the session-owner SSE stream, never in logs or Langfuse traces).

Run/review are Server-Sent-Event streams carrying two event families:
lifecycle (node_finished / awaiting_review / done / error) and activity —
the genuine agent feed (evidence_scan / model_thinking / finding / web_lookup)
emitted by nodes from real state and real model reasoning (FR9).

The graph checkpoints to SQLite so the human-review interrupt survives
process reloads; the in-memory _SESSIONS dict is only a pre-run buffer
(intake + uploaded evidence before the first run).
"""
import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.config import get_settings
from app.observability import request_trace
from app.schemas import (
    ApiResponse,
    EvidenceDocRecord,
    EvidenceMatrix,
    IntakeAnswers,
    ScreenerReport,
    VisaType,
)
from app.screener.evidence import extract_evidence_document
from app.screener.graph import build_graph
from app.screener.state import ScreenerState
from app.storage.base import get_store

logger = logging.getLogger("yunaki.screener.api")

router = APIRouter(prefix="/api/screener")

# Pre-run buffer only: intake + evidence between upload and the first run.
# Everything after run start lives in the SQLite checkpointer.
_SESSIONS: dict[str, "SessionRecord"] = {}
_MAX_SESSIONS = 200

_GRAPH = None
_GRAPH_LOCK = asyncio.Lock()


class SessionRecord(BaseModel):
    session_id: str
    visa_targets: list[VisaType] = Field(default_factory=lambda: ["O1A", "EB1A"])
    intake: IntakeAnswers | None = None
    evidence_docs: list[EvidenceDocRecord] = Field(default_factory=list)


class IntakeRequest(BaseModel):
    visa_targets: list[VisaType] = Field(
        default_factory=lambda: ["O1A", "EB1A"], min_length=1
    )
    intake: IntakeAnswers


class ReviewRequest(BaseModel):
    matrix: EvidenceMatrix


async def _get_graph():
    """Compiled graph over the SQLite checkpointer, created once per process.
    The connection lives for the process lifetime (local-first app; the OS
    reclaims it on exit)."""
    global _GRAPH
    if _GRAPH is None:
        async with _GRAPH_LOCK:
            if _GRAPH is None:
                import aiosqlite
                from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

                path = Path(get_settings().screener_checkpoint_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                conn = await aiosqlite.connect(str(path))
                _GRAPH = build_graph(checkpointer=AsyncSqliteSaver(conn))
                logger.info("screener graph ready checkpoint=%s", path)
    return _GRAPH


def _thread_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _json_error(message: str) -> ApiResponse:
    return ApiResponse(success=False, error=message)


@router.post("/session")
async def create_session(request: Request) -> ApiResponse:
    with request_trace("screener.session", request.headers.get("x-session-id")):
        if len(_SESSIONS) >= _MAX_SESSIONS:
            del _SESSIONS[next(iter(_SESSIONS))]
        session_id = uuid.uuid4().hex
        _SESSIONS[session_id] = SessionRecord(session_id=session_id)
        logger.info("screener session created id=%s", session_id)
        return ApiResponse(success=True, data={"session_id": session_id})


@router.put("/session/{session_id}/intake")
async def put_intake(session_id: str, req: IntakeRequest, request: Request) -> ApiResponse:
    with request_trace(
        "screener.intake",
        request.headers.get("x-session-id"),
        metadata={"visa_targets": ",".join(req.visa_targets)},
    ):
        record = _SESSIONS.get(session_id)
        if record is None:
            return _json_error("Unknown screener session.")
        _SESSIONS[session_id] = record.model_copy(
            update={"intake": req.intake, "visa_targets": req.visa_targets}
        )
        return ApiResponse(success=True, data={"session_id": session_id})


async def _read_capped(upload: UploadFile, max_bytes: int) -> bytes | None:
    """Chunk-read without buffering past the cap (Content-Length may lie)."""
    if upload.size is not None and upload.size > max_bytes:
        return None
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def _extract_evidence_slot(
    upload: UploadFile, expected_kind: str | None
) -> EvidenceDocRecord | dict:
    """One evidence upload → record | {"error": ...} (slot isolation: one bad
    file never discards another's extraction)."""
    settings = get_settings()
    content = await _read_capped(upload, settings.max_file_mb * 1024 * 1024)
    if content is None:
        return {"error": f"File exceeds the {settings.max_file_mb} MB limit."}
    try:
        record = await extract_evidence_document(
            content, upload.filename or "", expected_kind  # type: ignore[arg-type]
        )
    except ValueError as exc:  # guardrail rejection — user-actionable
        return {"error": str(exc)}
    try:
        await get_store().save_document(content, "evidence", upload.filename or "")
    except Exception:
        logger.exception("evidence persistence failed hash=%s", record.source_hash)
    return record


@router.post("/session/{session_id}/documents")
async def upload_documents(
    session_id: str,
    request: Request,
    resume: UploadFile | None = None,
    evidence: list[UploadFile] | None = None,
) -> ApiResponse:
    """Resume + evidence uploads, extracted synchronously (fast guardrail
    feedback) and buffered on the session for the run."""
    settings = get_settings()
    record = _SESSIONS.get(session_id)
    if record is None:
        return _json_error("Unknown screener session.")
    evidence = evidence or []
    if resume is None and not evidence:
        return _json_error("Upload a resume or at least one evidence document.")
    if len(evidence) > settings.screener_max_evidence_docs:
        return _json_error(
            f"At most {settings.screener_max_evidence_docs} evidence documents "
            "per session."
        )
    with request_trace(
        "screener.documents",
        request.headers.get("x-session-id"),
        metadata={"has_resume": resume is not None, "evidence_count": len(evidence)},
    ) as trace:
        data: dict = {"evidence": []}
        new_docs: list[EvidenceDocRecord] = list(record.evidence_docs)

        if resume is not None:
            result = await _extract_evidence_slot(resume, "resume")
            if isinstance(result, dict):
                data["resume"] = result
            else:
                data["resume"] = result.model_dump()
                new_docs = [d for d in new_docs if d.document_kind_detected != "resume"]
                new_docs.append(result)

        for upload in evidence:
            result = await _extract_evidence_slot(upload, None)
            if isinstance(result, dict):
                data["evidence"].append(result)
            else:
                data["evidence"].append(result.model_dump())
                new_docs = [d for d in new_docs if d.source_hash != result.source_hash]
                new_docs.append(result)

        _SESSIONS[session_id] = record.model_copy(update={"evidence_docs": new_docs})
        if trace is not None:
            trace.update(
                output={
                    "docs_buffered": len(new_docs),
                    "rejected": sum(
                        1 for slot in [data.get("resume"), *data["evidence"]]
                        if isinstance(slot, dict) and "error" in slot
                    ),
                }
            )
        return ApiResponse(success=True, data=data)


async def _event_stream(graph, config: dict, input_obj) -> AsyncIterator[str]:
    """Graph execution → SSE. Lifecycle events from `updates` mode, the
    genuine activity feed from `custom` mode. PII goes only to this stream
    (the session owner's own data); traces stay masked."""
    yield _sse({"event": "run_started"})
    try:
        async for mode, payload in graph.astream(
            input_obj, config=config, stream_mode=["updates", "custom"]
        ):
            if mode == "custom":
                yield _sse({"event": "activity", **payload})
                continue
            for node, delta in payload.items():
                if node == "__interrupt__":
                    interrupt_value = delta[0].value if delta else {}
                    yield _sse(
                        {
                            "event": "awaiting_review",
                            "matrix": interrupt_value.get("matrix"),
                        }
                    )
                else:
                    yield _sse({"event": "node_finished", "node": node})
        snapshot = await graph.aget_state(config)
        report = (snapshot.values or {}).get("report")
        if report is not None:
            if not isinstance(report, ScreenerReport):
                report = ScreenerReport.model_validate(report)
            yield _sse({"event": "done", "report": report.model_dump()})
    except Exception:
        logger.exception("screener stream failed")
        yield _sse(
            {"event": "error", "message": "Screener run failed. Check server logs."}
        )


@router.post("/session/{session_id}/run")
async def run(session_id: str, request: Request):
    """Start the graph; stream progress. Ends with awaiting_review (HITL) —
    resume via POST .../review."""
    record = _SESSIONS.get(session_id)
    if record is None:
        return _json_error("Unknown screener session.")
    if record.intake is None:
        return _json_error("Submit the intake questionnaire first.")
    graph = await _get_graph()
    state = ScreenerState(
        session_id=session_id,
        live_feed=True,  # SSE run: enables the thought-summary streaming path
        visa_targets=record.visa_targets,
        intake=record.intake,
        evidence_docs=record.evidence_docs,
    )
    logger.info(
        "screener run start session=%s docs=%d targets=%s",
        session_id, len(record.evidence_docs), ",".join(record.visa_targets),
    )
    return StreamingResponse(
        _event_stream(graph, _thread_config(session_id), state),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/session/{session_id}/review")
async def review(session_id: str, req: ReviewRequest, request: Request):
    """Resume the interrupted run with the human-reviewed matrix; the edited
    matrix re-validates through the same schema and the same source audit.
    Session existence is checked against the checkpointer, so review survives
    a backend reload mid-HITL."""
    graph = await _get_graph()
    config = _thread_config(session_id)
    snapshot = await graph.aget_state(config)
    if snapshot is None or not snapshot.values:
        return _json_error("No run to resume for this session.")
    if not snapshot.next:
        return _json_error("This session is not awaiting review.")
    logger.info("screener review resume session=%s claims=%d", session_id, len(req.matrix.items))
    return StreamingResponse(
        _event_stream(graph, config, Command(resume=req.matrix.model_dump())),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/session/{session_id}/report")
async def report(session_id: str, request: Request) -> ApiResponse:
    with request_trace("screener.report", request.headers.get("x-session-id")):
        graph = await _get_graph()
        snapshot = await graph.aget_state(_thread_config(session_id))
        if snapshot is None or not snapshot.values:
            return _json_error("Unknown screener session or no run yet.")
        stored = snapshot.values.get("report")
        if stored is None:
            return _json_error("No report yet — the run has not completed.")
        if not isinstance(stored, ScreenerReport):
            stored = ScreenerReport.model_validate(stored)
        return ApiResponse(success=True, data=stored.model_dump())
