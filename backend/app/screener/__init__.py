"""Screener plane — O-1A / EB-1A eligibility decision support.

Contract: intake answers (+ evidence docs and web corroboration in later
phases) → LangGraph run → ScreenerReport with per-criterion verdicts, every
claim citation-audited against what the user actually provided. Decision
support only; the report always carries the attorney-review disclaimer.
"""
from app.screener.graph import build_graph

__all__ = ["build_graph"]
