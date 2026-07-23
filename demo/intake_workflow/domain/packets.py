"""Form-preparation packets: map accepted checklist data into USCIS form
field layouts, ready for filing transcription.

FROZEN CONTRACT: signatures and docstrings are the interface; bodies are
implemented by the phase-3 domain agent.

Null over guess is absolute here: a missing answer renders as an empty value
and is listed under ``missing`` — the packet must never fabricate, infer, or
default a value the client did not provide. Only ACCEPTED items feed packets
(the paralegal's accept is the data gate).
"""
from __future__ import annotations

from intake_workflow.schemas import Case, ItemState

# Form types the prototype can assemble. Field maps live in the implementation
# (one ordered section list per form) and may only source from: party
# full_name/email, accepted question-section answers, and case metadata.
FORM_TYPES: tuple[str, ...] = ("I-130", "I-485")

# Ordered field maps. Each field is (label, item_key, field_key); the source
# string is "item_key.field_key". Sources draw only from accepted
# question-section answers — no other data source is consulted.
_I130_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Part 1 — Petitioner", [
        ("Full legal name", "pet_bio", "full_name"),
        ("Home address", "pet_bio", "address"),
        ("Phone number", "pet_bio", "phone"),
    ]),
    ("Part 2 — Beneficiary", [
        ("Beneficiary full legal name", "ben_bio", "full_name"),
        ("Beneficiary date of birth", "ben_bio", "dob"),
        ("Beneficiary A-number", "ben_bio", "a_number"),
        ("Beneficiary I-94 number", "ben_bio", "i94_number"),
        ("Beneficiary date of last U.S. entry", "ben_bio", "last_entry"),
        ("Beneficiary current immigration status", "ben_bio", "current_status"),
        ("Beneficiary current address", "ben_address_history", "current_address"),
    ]),
    ("Part 3 — Marriage", [
        ("Date of marriage", "marriage_details", "marriage_date"),
        ("Place of marriage", "marriage_details", "marriage_place"),
        ("Prior marriages", "marriage_details", "prior_marriages"),
    ]),
]

_I485_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Part 1 — Applicant", [
        ("Full legal name", "ben_bio", "full_name"),
        ("Date of birth", "ben_bio", "dob"),
        ("Current address", "ben_address_history", "current_address"),
        ("Date moved into current address", "ben_address_history", "moved_in"),
    ]),
    ("Part 2 — Immigration history", [
        ("Date of last U.S. entry", "ben_bio", "last_entry"),
        ("Current immigration status", "ben_bio", "current_status"),
        ("A-number", "ben_bio", "a_number"),
        ("I-94 number", "ben_bio", "i94_number"),
    ]),
    ("Part 3 — Marriage", [
        ("Date of marriage", "marriage_details", "marriage_date"),
        ("Place of marriage", "marriage_details", "marriage_place"),
        ("Prior marriages", "marriage_details", "prior_marriages"),
    ]),
]

_FORM_MAPS: dict[str, list[tuple[str, list[tuple[str, str, str]]]]] = {
    "I-130": _I130_SECTIONS,
    "I-485": _I485_SECTIONS,
}


def _accepted_answers(case: Case) -> dict[str, dict[str, str]]:
    """item_key -> latest-submission answers, for ACCEPTED question sections only.

    The paralegal's accept is the data gate: anything not accepted contributes
    no values, so its fields fall through to "" and land in ``missing``.
    """
    out: dict[str, dict[str, str]] = {}
    for item in case.items:
        if item.state == ItemState.accepted and item.submissions:
            answers = item.submissions[-1].answers
            if answers:
                out[item.key] = answers
    return out


def build_packet(case: Case, form_type: str) -> dict:
    """Assemble the form-preparation packet for ``form_type``.

    Returns::

        {
          "form_type": "I-130",
          "case_title": ...,
          "sections": [
            {"title": "Part 1 — Petitioner",
             "fields": [{"label": "Full legal name",
                         "value": "Ana Marquez",
                         "source": "pet_bio.full_name"}, ...]},
            ...
          ],
          "missing": ["Beneficiary A-number", ...],   # labels with no data
        }

    - value "" (and a ``missing`` entry) whenever the source answer is
      absent, blank, or its item is not ``accepted``
    - ``source`` names where the value came from (item_key.field_key or
      "party.petitioner.full_name") for auditability
    - ValueError for an unknown form_type (message lists FORM_TYPES)
    """
    sections_map = _FORM_MAPS.get(form_type)
    if sections_map is None:
        raise ValueError(
            f"Unknown form_type {form_type!r}. "
            f"Supported: {', '.join(FORM_TYPES)}."
        )

    accepted = _accepted_answers(case)
    sections: list[dict] = []
    missing: list[str] = []

    for title, fields in sections_map:
        rendered: list[dict] = []
        for label, item_key, field_key in fields:
            answers = accepted.get(item_key) or {}
            value = (answers.get(field_key) or "").strip()
            if not value:
                # Null over guess: never fabricate, infer, or default a value.
                value = ""
                missing.append(label)
            rendered.append(
                {"label": label, "value": value,
                 "source": f"{item_key}.{field_key}"}
            )
        sections.append({"title": title, "fields": rendered})

    return {
        "form_type": form_type,
        "case_title": case.title,
        "sections": sections,
        "missing": missing,
    }
