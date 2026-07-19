"""Kernel — the shared runtime every workflow package builds on.

Extracted from the screener plane (Phase 1 of the OS build): the pieces here
are package-agnostic by contract. Nothing in this package may import from
app.screener, app.extraction, or app.population — dependencies point inward
only (kernel ← packages), never outward.

Modules:
- llm            structured Gemini calls (retry/validation/tracing) + client factory
- observability  Langfuse tracing primitives + PII maskers (no-op without keys)
"""
