"""Golden screener test — one live persona end to end. Skips (not fails)
without a Gemini key, exactly like test_extraction_golden.py."""
import os

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import get_settings
from app.screener.graph import build_graph
from app.screener.state import ScreenerState
from validation.screener_personas import PERSONAS

pytestmark = pytest.mark.skipif(
    not (os.environ.get("GEMINI_API_KEY") or get_settings().gemini_api_key),
    reason="GEMINI_API_KEY not set — golden screener test needs live Gemini",
)


async def test_unqualified_persona_yields_no_overclaims(monkeypatch):
    """The fabrication-bait persona (self-described 'thought leader', zero
    evidence) must come back with no met/likely anywhere and a
    not_recommended verdict — the anti-fabrication contract, live."""
    monkeypatch.setenv("SCREENER_WEB_ENRICHMENT", "false")
    get_settings.cache_clear()
    try:
        persona = next(p for p in PERSONAS if p.name == "08-fabrication-bait-empty-record")
        graph = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "golden-screener"}}
        state = ScreenerState(
            session_id="golden-screener",
            visa_targets=list(persona.visa_targets),
            intake=persona.intake,
        )
        first = await graph.ainvoke(state, config=config)
        assert "__interrupt__" in first
        matrix = first["__interrupt__"][0].value["matrix"]
        final = await graph.ainvoke(Command(resume=matrix), config=config)
        report = final["report"]

        overclaims = [
            (a.criterion_id, a.verdict)
            for a in report.assessments
            if a.verdict in ("met", "likely")
        ]
        assert overclaims == [], f"screener overclaimed on empty record: {overclaims}"
        for verdict in report.verdicts:
            assert verdict.recommendation in ("not_recommended", "weak"), verdict
        assert "not a legal determination" in report.disclaimer
    finally:
        get_settings.cache_clear()
