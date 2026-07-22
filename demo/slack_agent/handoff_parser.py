"""Parse a free-text case handoff via ONE Anthropic structured-output call.

CLAUDE_WORKPLAN.md §2 item 2. Model `claude-haiku-4-5`, temperature 0, tool-use
forced so the model must return the schema. NULL OVER GUESS is the prime
directive (§4.3): the prompt tells the model that any field not explicitly
present in the message is null, never inferred. A null is correct; a plausible
guess is a defect.

If ANTHROPIC_API_KEY is absent the parser does NOT call out — it returns an
all-null result with available=False, and the listener replies that parsing is
unavailable and asks for the fields. No PII is logged (§4.4): we log lengths and
counts, never the message body or the parsed names.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from core import config

logger = logging.getLogger("slack_agent.handoff_parser")

_MODEL = "claude-haiku-4-5"

_SYSTEM = (
    "You extract structured fields from an immigration paralegal's free-text "
    "case-handoff message. Return ONLY the record_handoff tool call.\n\n"
    "PRIME DIRECTIVE — NULL OVER GUESS: any field not explicitly present in the "
    "message MUST be null. Never infer, complete, or normalize a value that "
    "isn't literally stated. A null is correct; a plausible guess is a defect.\n"
    "- process_type: the immigration process/visa type only if stated, else null.\n"
    "- role: 'petitioner' for the U.S.-side sponsor/filer; 'beneficiary' for the "
    "spouse/relative being sponsored. Infer role ONLY from explicit relationship "
    "words (e.g. 'spouse', 'beneficiary', 'petitioner'); if unclear, still pick "
    "the best of the two enum values but leave every other field null.\n"
    "- first_name/last_name/email/phone: copy verbatim if present, else null. "
    "Do not split a single given name into a fake last name."
)

_TOOL = {
    "name": "record_handoff",
    "description": "Record the parsed handoff. Absent fields MUST be null.",
    "input_schema": {
        "type": "object",
        "properties": {
            "process_type": {"type": ["string", "null"]},
            "parties": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "enum": ["petitioner", "beneficiary"]},
                        "first_name": {"type": ["string", "null"]},
                        "last_name": {"type": ["string", "null"]},
                        "email": {"type": ["string", "null"]},
                        "phone": {"type": ["string", "null"]},
                    },
                    "required": ["role", "first_name", "last_name", "email", "phone"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["process_type", "parties"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class HandoffParty:
    role: str
    first_name: str | None
    last_name: str | None
    email: str | None
    phone: str | None


@dataclass(frozen=True)
class HandoffParse:
    process_type: str | None
    parties: list[HandoffParty] = field(default_factory=list)
    available: bool = True


def _all_null(available: bool) -> HandoffParse:
    return HandoffParse(process_type=None, parties=[], available=available)


def _party_from_dict(raw: dict) -> HandoffParty | None:
    role = raw.get("role")
    if role not in ("petitioner", "beneficiary"):
        return None

    def clean(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    return HandoffParty(
        role=role,
        first_name=clean(raw.get("first_name")),
        last_name=clean(raw.get("last_name")),
        email=clean(raw.get("email")),
        phone=clean(raw.get("phone")),
    )


def _parse_tool_input(tool_input: dict) -> HandoffParse:
    process_type = tool_input.get("process_type")
    if isinstance(process_type, str):
        process_type = process_type.strip() or None
    else:
        process_type = None
    parties: list[HandoffParty] = []
    for raw in tool_input.get("parties") or []:
        if isinstance(raw, dict):
            party = _party_from_dict(raw)
            if party is not None:
                parties.append(party)
    return HandoffParse(process_type=process_type, parties=parties, available=True)


def _call_anthropic(api_key: str, text: str) -> HandoffParse:
    """Blocking Anthropic call. Run via asyncio.to_thread from the async path."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        temperature=0,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "record_handoff"},
        messages=[{"role": "user", "content": text}],
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "record_handoff":
            tool_input = block.input
            if isinstance(tool_input, str):
                tool_input = json.loads(tool_input)
            return _parse_tool_input(tool_input)
    # Model returned no tool call — treat as unparseable, invent nothing.
    logger.warning("handoff parser: no tool_use block returned")
    return _all_null(available=True)


async def parse_handoff(text: str) -> HandoffParse:
    """Parse a handoff message. Never raises to the caller; fails to all-nulls."""
    api_key = config.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.info("handoff parser unavailable: ANTHROPIC_API_KEY unset")
        return _all_null(available=False)
    try:
        result = await asyncio.to_thread(_call_anthropic, api_key, text)
        logger.info(
            "handoff parsed: process_type_known=%s parties=%d",
            result.process_type is not None,
            len(result.parties),
        )
        return result
    except Exception:  # noqa: BLE001 - fail loud in logs, safe (all-null) to caller
        logger.exception("handoff parse failed; returning all-null")
        return _all_null(available=True)
