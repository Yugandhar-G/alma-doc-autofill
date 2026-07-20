"""Ask-the-matter research agent — NOT a graph.

A single bounded firm-data loop over ALL five corpus tools, distilled into a
flat ResearchAnswer and deterministically audited: every ref must be in
transcript.seen_refs. If every ref is stripped and the model did not mark the
question unanswerable, the answer text is replaced with an honest
cannot-substantiate message — the null-discipline analog (a "cannot answer" is
correct; a plausible ungrounded answer is a defect).

v1 returns a sync JSON answer. The live SSE thinking feed (the agent narrating
its firm-data reads) is a shell follow-up; the transcript already records every
step, so the feed is additive, not a contract change here."""
import logging

from app.config import Settings
from app.kernel.store.base import MatterStore, TenantScope
from app.packages.matter_intake import loop
from app.packages.matter_intake.prompts import ask_distill_prompt, ask_task_prompt
from app.packages.matter_intake.refs_audit import surviving_refs
from app.packages.matter_intake.schemas import ResearchAnswer

logger = logging.getLogger("yunaki.matter_intake.ask")

_GRANTS = (
    "list_matter_docs",
    "read_extraction",
    "read_run_report",
    "recall_memory",
    "search_matter_corpus",
)
_MAX_TOOL_CALLS = 12
_CANNOT_SUBSTANTIATE = (
    "I could not substantiate an answer from this matter's records. Nothing in "
    "the firm's documents, prior runs, or memory supports a grounded answer to "
    "that question."
)


def audit_answer(answer: ResearchAnswer, seen_refs: list[str]) -> ResearchAnswer:
    """Strip refs the agent never saw. If none survive AND the model did not
    already declare the question unanswerable, refuse honestly rather than
    return an ungrounded answer."""
    kept = surviving_refs(answer.refs, seen_refs)
    if not kept and not answer.unanswerable:
        return answer.model_copy(
            update={"refs": [], "text": _CANNOT_SUBSTANTIATE, "unanswerable": True}
        )
    return answer.model_copy(update={"refs": kept})


async def ask_matter(
    scope: TenantScope,
    matter_id: str,
    question: str,
    settings: Settings,
    store: MatterStore,
) -> ResearchAnswer:
    """Run the firm-data loop, distill, and audit. Returns the grounded answer."""
    transcript = await loop.run_firm_agent(
        scope=scope, store=store, settings=settings,
        prompt=ask_task_prompt(matter_id, question, _MAX_TOOL_CALLS),
        grants=_GRANTS, max_tool_calls=_MAX_TOOL_CALLS, node="ask_matter",
    )
    answer: ResearchAnswer = await loop.distill(
        settings,
        ask_distill_prompt(question, transcript.log, transcript.seen_refs),
        ResearchAnswer,
        trace_name="gemini.matter_intake.ask.distill",
    )
    audited = audit_answer(answer, transcript.seen_refs)
    logger.info(
        "ask matter=%s refs_kept=%d unanswerable=%s",
        matter_id, len(audited.refs), audited.unanswerable,
    )
    return audited
