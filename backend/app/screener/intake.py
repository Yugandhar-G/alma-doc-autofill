"""Intake answer addressing. Field names are the answer_id namespace:
scalar fields cite as "field_of_endeavor", list entries as "awards[0]".
The frontend renders the questionnaire from the same ids (TS mirror), so a
SourceRef(kind="answer") is verifiable end to end."""
import re

from app.schemas import IntakeAnswers

_LIST_REF = re.compile(r"^([a-z_]+)\[(\d+)\]$")


def answer_index(intake: IntakeAnswers) -> dict[str, str]:
    """answer_id → answer text, for every non-empty answer."""
    index: dict[str, str] = {}
    for name, value in intake.model_dump().items():
        if isinstance(value, list):
            for i, entry in enumerate(value):
                if entry and str(entry).strip():
                    index[f"{name}[{i}]"] = str(entry)
        elif value is not None and str(value).strip():
            index[name] = str(value)
    return index


def render_intake(intake: IntakeAnswers) -> str:
    """The questionnaire as prompt text, each answer prefixed with the exact
    answer_id the model must cite. Empty answers are omitted (nothing to cite)."""
    lines = [
        f"[{answer_id}] {text}" for answer_id, text in answer_index(intake).items()
    ]
    return "\n".join(lines) if lines else "(no intake answers provided)"


def is_valid_answer_ref(ref: str, valid_ids: frozenset[str] | set[str]) -> bool:
    """True when ref names an answer the user actually gave."""
    if ref in valid_ids:
        return True
    # Tolerate a bare list name citing the whole list (e.g. "awards") when at
    # least one entry exists — the claim is still user-sourced.
    return any(
        (m := _LIST_REF.match(existing)) is not None and m.group(1) == ref
        for existing in valid_ids
    )
