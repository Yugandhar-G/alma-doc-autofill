"""Flat, Gemini-safe response schemas + checkpointed graph state for the
RFE-response assembler.

Every model a node hands to Gemini as a ``response_schema`` (RfeNotice on the
vision call, ResponseChecklist on the distillation call) is FLAT — no
discriminated unions, no maxItems on lists of nested models — and is listed in
tests/test_schema_lint.py, the same discipline the screener / matter-intake
schemas follow. RfeResponseReport is a pure-code artifact (no model ever emits
it), but it is kept lint-clean and registered so a future phase that drafts it
via a model inherits a Gemini-safe schema.

Extraction contract (mirrors CLAUDE.md): every RfeNotice scalar is Optional with
default None — an absent / illegible receipt number, form id, notice date, or
deadline stays None. A null is correct; a plausible guess is a defect.

The state model carries firm/matter/run ids + the run-time artifacts. It is
checkpointed by LangGraph, so it holds only serializable data (never a store
handle or a TenantScope — those are reconstructed in-node from the ids)."""
from pydantic import BaseModel, Field


# --- Extraction contracts (RfeNotice is handed to Gemini directly) ----------
class RfeGround(BaseModel):
    """One ground of the RFE — a discrete deficiency the officer raised.

    ``quoted_text`` MUST be a verbatim transcription of the notice (the checklist
    audit and the human reviewer both rely on it being the officer's own words,
    never a paraphrase). ``requested_evidence`` is the officer's description of
    what would cure the ground."""

    ground_id: str = Field(description="Stable id for this ground (g1, g2, ...)")
    quoted_text: str = Field(description="Verbatim excerpt of the ground from the notice")
    requested_evidence: str = Field(description="Evidence the officer requests to cure it")


class RfeNotice(BaseModel):
    """The parsed RFE notice. Every scalar is Optional/None-defaulted — an
    illegible or absent field stays None, never guessed. ``grounds`` come back
    in this same structured vision call (no second LLM call), so parse_grounds
    is pure-code normalization, not another model round-trip."""

    receipt_number: str | None = None
    form_id: str | None = Field(None, description="The petition form, e.g. I-129, I-140")
    notice_date: str | None = Field(None, description="Notice date, normalized YYYY-MM-DD")
    response_deadline: str | None = Field(
        None, description="Response-by date, normalized YYYY-MM-DD"
    )
    grounds: list[RfeGround] = Field(default_factory=list)


# --- Checklist distillation contract (ResponseChecklist is handed to Gemini) -
class ChecklistItem(BaseModel):
    """One response action mapped to a ground. ``doc_kinds`` are the kinds of
    document the action would gather; ``refs`` cite the ground_id it addresses
    and/or matter doc ids surfaced in the prompt. Every ref is audited in pure
    code against {ground_ids} ∪ {matter doc ids} — an invented ref is stripped
    and an item citing a ground that does not exist is dropped."""

    ground_id: str
    action: str
    doc_kinds: list[str] = Field(default_factory=list)
    refs: list[str] = Field(default_factory=list)


class ResponseChecklist(BaseModel):
    """The assembled response plan. ``items`` come from the distillation call
    (then audited); ``cover_structure`` is assembled in CODE from the surviving
    items — ordered section headings, one per addressed ground — never free
    LLM prose."""

    items: list[ChecklistItem] = Field(default_factory=list)
    cover_structure: list[str] = Field(default_factory=list)


# --- Report (pure-code artifact; lint-clean, never model-emitted) -----------
class RfeResponseReport(BaseModel):
    """The assembled RFE-response report shown at review and finalized after.

    ``ok`` is True only when the deadline is verifiable and safe (>= 14 days
    remaining) AND every parsed ground is covered by at least one audited
    checklist item — the assembler is honest about being unable to confirm a
    deadline or about a ground left unaddressed."""

    notice: RfeNotice
    deadline_days_remaining: int | None = None
    deadline_warning: str | None = None
    checklist: ResponseChecklist
    ok: bool = False


# --- Checkpointed graph state -----------------------------------------------
class RfeResponseState(BaseModel):
    """RFE-response graph state. firm/user/matter ids reconstitute the
    TenantScope in-node (a store handle cannot be checkpointed); matter_id is
    optional — a notice-only run has no matter context, so finalize skips the
    firm-memory write. ``today`` is injected by the API at run start so the
    deadline node stays deterministic and replayable (never datetime.now())."""

    run_id: str = ""
    firm_id: str | None = None
    user_id: str | None = None
    matter_id: str | None = None
    matter_type: str = "immigration"
    today: str = ""
    # Raw notice bytes flow in only between START and extract_notice, which
    # clears them (returns None) so they never reach the review checkpoint.
    notice_bytes: bytes | None = None
    notice_filename: str = ""
    notice: RfeNotice | None = None
    deadline_days_remaining: int | None = None
    deadline_warning: str | None = None
    checklist: ResponseChecklist | None = None
    warnings: list[str] = Field(default_factory=list)
    report: RfeResponseReport | None = None
