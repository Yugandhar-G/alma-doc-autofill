"""Compatibility shim — the fetch driver and SSRF guards moved to
app.kernel.tools (Phase 1 of the OS build). Import from app.kernel.tools in
new code.
"""
from app.kernel.tools.fetch_page import MAX_PAGE_CHARS, fetch_page  # noqa: F401
from app.kernel.tools.guards import check_url_allowed, html_to_text  # noqa: F401
