"""Shared Jinja2 environment for the web layer.

One ``Jinja2Templates`` instance, pointed at ``app/templates`` (resolved from
this file so it is independent of the process CWD), plus a small set of
presentation helpers registered as globals/filters so templates stay dumb:
routers do the domain calls, templates only render.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _enum_value(x: Any) -> str:
    return getattr(x, "value", x)


# Checklist item state -> (client-friendly label, staff label, css modifier)
_STATE_META: dict[str, dict[str, str]] = {
    "pending":   {"label": "To-do",             "staff": "Awaiting client",   "cls": "chip--pending"},
    "submitted": {"label": "Submitted",         "staff": "Submitted",          "cls": "chip--submitted"},
    "flagged":   {"label": "Needs a fix",       "staff": "Auto-check flagged", "cls": "chip--flagged"},
    "checked":   {"label": "Received",          "staff": "Auto-check passed",  "cls": "chip--checked"},
    "returned":  {"label": "Please re-send",    "staff": "Returned to client", "cls": "chip--returned"},
    "accepted":  {"label": "Accepted",          "staff": "Accepted",           "cls": "chip--accepted"},
}

_STAGE_META: dict[str, dict[str, str]] = {
    "sent":             {"label": "Sent",             "cls": "badge--sent"},
    "opened":           {"label": "Opened",           "cls": "badge--opened"},
    "in_progress":      {"label": "In progress",      "cls": "badge--progress"},
    "stalled":          {"label": "Stalled",          "cls": "badge--stalled"},
    "ready_for_review": {"label": "Ready for review", "cls": "badge--ready"},
    "complete":         {"label": "Complete",         "cls": "badge--complete"},
}

_RUNG_META: dict[str, str] = {
    "nudge":      "Day 3 · friendly nudge",
    "specifics":  "Day 7 · item specifics",
    "call_offer": "Day 12 · offer a call",
    "escalate":   "Day 18 · escalate to attorney",
}

_RADAR_META: dict[str, dict[str, str]] = {
    "window_open": {"label": "Filing window open", "cls": "badge--stalled"},
    "collect_now": {"label": "Collect documents",  "cls": "badge--progress"},
    "upcoming":    {"label": "Upcoming",           "cls": "badge--sent"},
}


def state_chip(state: Any, staff: bool = False) -> dict[str, str]:
    meta = _STATE_META.get(_enum_value(state), {"label": _enum_value(state), "staff": _enum_value(state), "cls": "chip--pending"})
    return {"label": meta["staff"] if staff else meta["label"], "cls": meta["cls"]}


def stage_badge(stage: Any) -> dict[str, str]:
    return _STAGE_META.get(_enum_value(stage), {"label": _enum_value(stage), "cls": "badge--sent"})


def rung_label(rung: Any) -> str:
    return _RUNG_META.get(_enum_value(rung), _enum_value(rung))


def radar_badge(status: Any) -> dict[str, str]:
    return _RADAR_META.get(_enum_value(status), {"label": _enum_value(status), "cls": "badge--sent"})


def fmt_dt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.strftime("%b %d, %Y · %I:%M %p").replace(" 0", " ")
    return str(value)


def fmt_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, (date, datetime)):
        return value.strftime("%b %d, %Y").replace(" 0", " ")
    return str(value)


templates.env.globals.update(
    state_chip=state_chip,
    stage_badge=stage_badge,
    rung_label=rung_label,
    radar_badge=radar_badge,
)
templates.env.filters.update(
    fmt_dt=fmt_dt,
    fmt_date=fmt_date,
)
