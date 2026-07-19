"""Compatibility shim — the LLM plumbing moved to app.kernel.llm (Phase 1 of
the OS build). Import from app.kernel.llm in new code; this module keeps the
old import path working until every consumer is repointed.
"""
from app.kernel.llm import (  # noqa: F401
    call_gemini,
    call_gemini_stream,
    make_client,
    safe_error_summary,
)
