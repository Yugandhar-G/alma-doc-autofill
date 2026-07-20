"""Kernel runtime — graph execution services every workflow package shares.

- checkpoints: checkpointer factory (SQLite now; Postgres when firm sync lands)
- manager:     compiled-graph registry replacing per-module _GRAPH globals
- runner:      run/resume → SSE event stream (lifecycle + activity families)
- scheduler:   per-firm-capped in-process executor (desktop model)
- workflows:   WorkflowService — matter-store ⇄ package-runtime run lifecycle
"""
from app.kernel.runtime.checkpoints import open_sqlite_checkpointer  # noqa: F401
from app.kernel.runtime.manager import RunManager  # noqa: F401
from app.kernel.runtime.runner import event_stream, sse, thread_config  # noqa: F401
from app.kernel.runtime.scheduler import Scheduler  # noqa: F401
from app.kernel.runtime.workflows import (  # noqa: F401
    WorkflowError,
    WorkflowService,
)
