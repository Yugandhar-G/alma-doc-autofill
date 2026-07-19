"""Compatibility shim — the grounded-search driver moved to
app.kernel.tools.web_search (Phase 1 of the OS build). Import from
app.kernel.tools in new code.
"""
from app.kernel.tools.web_search import grounded_search  # noqa: F401
