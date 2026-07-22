"""handoff_parser unit tests — NULL OVER GUESS + no-key behavior."""

from __future__ import annotations

import asyncio

from slack_agent import handoff_parser
from slack_agent.handoff_parser import parse_handoff


def test_no_api_key_returns_all_null_and_unavailable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = asyncio.run(parse_handoff("New marriage case, Ravi and spouse Mei"))
    assert result.available is False
    assert result.process_type is None
    assert result.parties == []


def test_parse_tool_input_keeps_absent_fields_null():
    tool_input = {
        "process_type": None,
        "parties": [
            {
                "role": "petitioner",
                "first_name": "Ravi",
                "last_name": None,
                "email": None,
                "phone": None,
            }
        ],
    }
    result = handoff_parser._parse_tool_input(tool_input)
    assert result.process_type is None
    assert len(result.parties) == 1
    party = result.parties[0]
    assert party.first_name == "Ravi"
    # Absent fields stay null — never invented.
    assert party.last_name is None
    assert party.email is None
    assert party.phone is None


def test_parse_tool_input_drops_invalid_role():
    tool_input = {
        "process_type": "N-400",
        "parties": [
            {"role": "witness", "first_name": "X", "last_name": None, "email": None, "phone": None}
        ],
    }
    result = handoff_parser._parse_tool_input(tool_input)
    assert result.parties == []


def test_parse_tool_input_blanks_become_null():
    tool_input = {
        "process_type": "   ",
        "parties": [
            {"role": "beneficiary", "first_name": "  ", "last_name": "Lin", "email": "", "phone": None}
        ],
    }
    result = handoff_parser._parse_tool_input(tool_input)
    assert result.process_type is None
    assert result.parties[0].first_name is None
    assert result.parties[0].email is None
    assert result.parties[0].last_name == "Lin"
