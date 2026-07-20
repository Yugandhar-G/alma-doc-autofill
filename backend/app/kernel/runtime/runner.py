"""Run/resume → SSE. One event contract for every workflow package:

lifecycle family: run_started / node_finished / awaiting_review / done / error
activity family:  whatever the package's nodes emit through the custom stream
                  (evidence_scan / model_thinking / finding / tool_call / ...)

PII channel rule: this stream goes to the session owner only (it carries
their own data and genuine model reasoning); traces stay masked. The error
event is deliberately generic — details go to server logs, never the wire."""
import json
import logging
from typing import Any, AsyncIterator

from pydantic import BaseModel

logger = logging.getLogger("yunaki.kernel.runner")


def thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def event_stream(
    graph: Any,
    config: dict,
    input_obj: Any,
    *,
    result_key: str = "report",
    result_model: type[BaseModel] | None = None,
    error_message: str = "Run failed. Check server logs.",
) -> AsyncIterator[str]:
    """Graph execution → SSE. Lifecycle events from `updates` mode, the
    genuine activity feed from `custom` mode. After the stream ends, the
    checkpointed state's `result_key` (if present) becomes the done event."""
    yield sse({"event": "run_started"})
    try:
        async for mode, payload in graph.astream(
            input_obj, config=config, stream_mode=["updates", "custom"]
        ):
            if mode == "custom":
                yield sse({"event": "activity", **payload})
                continue
            for node, delta in payload.items():
                if node == "__interrupt__":
                    # The interrupt payload is package-defined (screener parks
                    # with {"matrix": ...}, autofill with envelopes); spread it
                    # so each package's review UI gets its own shape.
                    interrupt_value = delta[0].value if delta else {}
                    yield sse({"event": "awaiting_review", **(interrupt_value or {})})
                else:
                    yield sse({"event": "node_finished", "node": node})
        snapshot = await graph.aget_state(config)
        result = (snapshot.values or {}).get(result_key)
        if result is not None:
            if result_model is not None and not isinstance(result, result_model):
                result = result_model.model_validate(result)
            if isinstance(result, BaseModel):
                result = result.model_dump()
            yield sse({"event": "done", result_key: result})
    except Exception:
        logger.exception("workflow stream failed")
        yield sse({"event": "error", "message": error_message})
