"""Firm-data tool layer — deterministic retrieval over the firm's own records.

The read side of the deep-agent substrate: a package agent granted these tools
can look up a matter's documents, read a stored extraction, read a prior run's
report, recall firm memory, and keyword-search the firm corpus. Pure retrieval,
NO LLM, NO network — the model decides WHAT to look up; code owns HOW it is
fetched and, above all, WHOSE data it may reach.

Tenancy is structural, not advisory. Every tool:
- refuses with a plain "TOOL_UNAVAILABLE: no firm scope" when ctx.scope or
  ctx.matter_store is None (a web-only agent that was never handed a firm scope
  simply cannot read firm data), and
- runs every query through the TenantScope INSIDE the tool, so a scope for
  firm B can never surface firm A's rows. read_extraction is content-addressed
  (the blob store is keyed by hash, not firm), so it additionally checks that
  the requested doc_id is indexed under one of the caller's own matters before
  returning anything — the same firm wall, enforced here rather than upstream.

Every tool records the refs it surfaced (memory ids, doc_ids, run_ids) into
transcript.seen_refs — the deterministic ground truth a firm-data transcript
audit runs against, exactly parallel to seen_urls for web agents — and appends
a PII-safe rendered line (counts + short ids, never filenames) to transcript.log
like the web tools do.

Nothing is registered globally. CORPUS_TOOLS is exported for a package to grant.
"""
import json

from google.genai import types as genai_types

from app.kernel.memory.service import MemoryService
from app.kernel.store.base import MatterStore, TenantScope
from app.kernel.tools.registry import ToolContext, ToolSpec
from app.storage.base import get_store  # module-level: test seam

# Every firm-data tool result is length-capped before it re-enters the model
# context — a large extraction or summary cannot blow the prompt budget.
_MAX_TOOL_CHARS = 4000
_UNAVAILABLE = "TOOL_UNAVAILABLE: no firm scope"


def _cap(text: str) -> str:
    return text if len(text) <= _MAX_TOOL_CHARS else text[:_MAX_TOOL_CHARS] + "\n…[truncated]"


def _compact_json(value: object) -> str:
    """Deterministic compact JSON; never raises on odd types (default=str)."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _record_ref(transcript, ref: str) -> None:
    """Append a surfaced firm-data ref to the transcript ground truth (deduped,
    order-preserving), mirroring how the web tools grow seen_urls."""
    if ref and ref not in transcript.seen_refs:
        transcript.seen_refs.append(ref)


def _firm_scope(ctx: ToolContext) -> tuple[TenantScope, MatterStore] | None:
    """(scope, store) when the agent was handed a firm context, else None —
    the single guard every tool applies before touching firm data."""
    if ctx.scope is None or ctx.matter_store is None:
        return None
    return ctx.scope, ctx.matter_store


async def _run_list_matter_docs(args: dict, ctx: ToolContext) -> str:
    firm = _firm_scope(ctx)
    if firm is None:
        return _UNAVAILABLE
    scope, store = firm
    matter_id = str(args.get("matter_id", ""))
    ctx.emit({"type": "tool_call", "node": ctx.node, "tool": "list_matter_docs", "matter": matter_id[:12]})
    docs = await store.list_documents(scope, matter_id)
    for doc in docs:
        _record_ref(ctx.transcript, doc.doc_id)
    if not docs:
        result = "NO_DOCUMENTS: no documents are attached to that matter (or the matter is not in your firm)."
    else:
        lines = [
            f"[doc:{doc.doc_id}] type={doc.doc_type} filename={doc.filename}"
            for doc in docs
        ]
        result = "\n".join(lines)
    ctx.transcript.log.append(f"list_matter_docs({matter_id[:12]!r}) -> {len(docs)} docs")
    ctx.emit({"type": "tool_result", "node": ctx.node, "tool": "list_matter_docs", "docs": len(docs)})
    return _cap(result)


async def _firm_doc_ids(scope: TenantScope, store: MatterStore) -> set[str]:
    """Every doc_id indexed under the caller's own matters — the firm wall for
    the content-addressed read_extraction (the blob store itself is not scoped)."""
    doc_ids: set[str] = set()
    for matter in await store.list_matters(scope):
        for doc in await store.list_documents(scope, matter.id):
            doc_ids.add(doc.doc_id)
    return doc_ids


async def _run_read_extraction(args: dict, ctx: ToolContext) -> str:
    firm = _firm_scope(ctx)
    if firm is None:
        return _UNAVAILABLE
    scope, store = firm
    doc_id = str(args.get("doc_id", ""))
    doc_type = str(args.get("doc_type", ""))
    ctx.emit({"type": "tool_call", "node": ctx.node, "tool": "read_extraction", "doc": doc_id[:12]})
    # Firm wall: content-addressed blobs are not firm-scoped, so refuse any
    # doc_id the caller's own matters do not index.
    if doc_id not in await _firm_doc_ids(scope, store):
        ctx.transcript.log.append(f"read_extraction({doc_id[:12]!r}) -> not in firm")
        return "NOT_FOUND: that document is not indexed in your firm."
    doc_store = get_store()
    envelope = await doc_store.get_extraction(doc_id, doc_type, "final")
    kind = "final"
    if envelope is None:
        envelope = await doc_store.get_extraction(doc_id, doc_type, "raw")
        kind = "raw"
    if envelope is None:
        ctx.transcript.log.append(f"read_extraction({doc_id[:12]!r},{doc_type}) -> none")
        return "NOT_FOUND: no extraction stored for that document/type."
    _record_ref(ctx.transcript, doc_id)
    result = _cap(_compact_json(envelope.model_dump(mode="json")))
    ctx.transcript.log.append(
        f"read_extraction({doc_id[:12]!r},{doc_type}) -> {kind} {len(result)} chars"
    )
    ctx.emit({"type": "tool_result", "node": ctx.node, "tool": "read_extraction", "kind": kind})
    return result


async def _run_read_run_report(args: dict, ctx: ToolContext) -> str:
    firm = _firm_scope(ctx)
    if firm is None:
        return _UNAVAILABLE
    scope, store = firm
    run_id = str(args.get("run_id", ""))
    ctx.emit({"type": "tool_call", "node": ctx.node, "tool": "read_run_report", "run": run_id[:12]})
    run = await store.get_run(scope, run_id)  # firm-scoped: None across the wall
    if run is None:
        ctx.transcript.log.append(f"read_run_report({run_id[:12]!r}) -> none")
        return "NOT_FOUND: no run in your firm with that id."
    _record_ref(ctx.transcript, run_id)
    result = _cap(_compact_json(run.summary_json))
    ctx.transcript.log.append(f"read_run_report({run_id[:12]!r}) -> {len(result)} chars")
    ctx.emit({"type": "tool_result", "node": ctx.node, "tool": "read_run_report", "status": run.status})
    return result


async def _run_recall_memory(args: dict, ctx: ToolContext) -> str:
    firm = _firm_scope(ctx)
    if firm is None:
        return _UNAVAILABLE
    scope, store = firm
    matter_type = args.get("matter_type") or None
    criterion_key = args.get("criterion_key") or None
    ctx.emit({"type": "tool_call", "node": ctx.node, "tool": "recall_memory",
              "matter_type": matter_type, "criterion_key": criterion_key})
    memory = ctx.memory or MemoryService(store)
    records = await memory.recall(scope, matter_type=matter_type, criterion_key=criterion_key)
    for record in records:
        _record_ref(ctx.transcript, record.id)
    result = _cap(MemoryService.render_for_prompt(records))
    ctx.transcript.log.append(f"recall_memory({matter_type},{criterion_key}) -> {len(records)} memories")
    ctx.emit({"type": "tool_result", "node": ctx.node, "tool": "recall_memory", "memories": len(records)})
    return result


async def _run_search_matter_corpus(args: dict, ctx: ToolContext) -> str:
    firm = _firm_scope(ctx)
    if firm is None:
        return _UNAVAILABLE
    scope, store = firm
    query = str(args.get("query", ""))
    ctx.emit({"type": "tool_call", "node": ctx.node, "tool": "search_matter_corpus", "query": query[:120]})
    tokens = [tok for tok in query.lower().split() if len(tok) >= 2]

    hits: list[str] = []
    # (a) firm memory summaries
    for record in await store.list_memories(scope, limit=200):
        haystack = f"{record.matter_type} {record.kind} {record.summary}".lower()
        if _matches(tokens, haystack):
            _record_ref(ctx.transcript, record.id)
            hits.append(f"[memory:{record.id}] {record.matter_type}/{record.kind} {record.summary}")
    # (b) matter document filenames + doc_types (firm-scoped scan)
    for matter in await store.list_matters(scope):
        for doc in await store.list_documents(scope, matter.id):
            haystack = f"{doc.doc_type} {doc.filename}".lower()
            if _matches(tokens, haystack):
                _record_ref(ctx.transcript, doc.doc_id)
                hits.append(f"[doc:{doc.doc_id}] type={doc.doc_type} filename={doc.filename}")

    result = "\n".join(hits) if hits else "NO_MATCHES: no firm records matched that query."
    ctx.transcript.log.append(f"search_matter_corpus({query[:60]!r}) -> {len(hits)} hits")
    ctx.emit({"type": "tool_result", "node": ctx.node, "tool": "search_matter_corpus", "hits": len(hits)})
    return _cap(result)


def _matches(tokens: list[str], haystack: str) -> bool:
    """v1 keyword match: any query token appearing as a substring. Honest and
    deterministic — this is a keyword scan, not semantic search."""
    return bool(tokens) and any(tok in haystack for tok in tokens)


def _obj(**properties: genai_types.Schema) -> genai_types.Schema:
    return genai_types.Schema(type=genai_types.Type.OBJECT, properties=properties)


def _str() -> genai_types.Schema:
    return genai_types.Schema(type=genai_types.Type.STRING)


CORPUS_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="list_matter_docs",
        description=(
            "List the documents attached to a matter in your firm. Returns each "
            "document's type, filename, and doc_id (content hash). Use the doc_id "
            "with read_extraction to read what was extracted from it."
        ),
        parameters=genai_types.Schema(
            type=genai_types.Type.OBJECT,
            properties={"matter_id": _str()},
            required=["matter_id"],
        ),
        run=_run_list_matter_docs,
    ),
    ToolSpec(
        name="read_extraction",
        description=(
            "Read the stored structured extraction for one document in your firm, "
            "by its doc_id (content hash) and document type (e.g. 'passport', "
            "'g28'). Returns the extraction as compact JSON. Only documents "
            "indexed in your firm's matters are readable."
        ),
        parameters=genai_types.Schema(
            type=genai_types.Type.OBJECT,
            properties={"doc_id": _str(), "doc_type": _str()},
            required=["doc_id", "doc_type"],
        ),
        run=_run_read_extraction,
    ),
    ToolSpec(
        name="read_run_report",
        description=(
            "Read the summary of a prior workflow run in your firm, by run_id. "
            "Returns the run's result summary as compact JSON."
        ),
        parameters=genai_types.Schema(
            type=genai_types.Type.OBJECT,
            properties={"run_id": _str()},
            required=["run_id"],
        ),
        run=_run_read_run_report,
    ),
    ToolSpec(
        name="recall_memory",
        description=(
            "Recall your firm's memory of past matters — recorded outcomes (RFEs, "
            "denials, approvals), reviewer edits, and notes — filtered optionally "
            "by matter_type and criterion_key, newest first. Each result is "
            "labeled [memory:<id>]; cite an id you actually saw here to ground a "
            "claim on firm history."
        ),
        parameters=_obj(matter_type=_str(), criterion_key=_str()),
        run=_run_recall_memory,
    ),
    ToolSpec(
        name="search_matter_corpus",
        description=(
            "Keyword-search your firm's records: memory summaries and matter "
            "document filenames/types. This is a keyword (substring) match over "
            "firm records, not semantic search — use specific terms. Returns "
            "labeled [memory:<id>] / [doc:<doc_id>] hits."
        ),
        parameters=genai_types.Schema(
            type=genai_types.Type.OBJECT,
            properties={"query": _str()},
            required=["query"],
        ),
        run=_run_search_matter_corpus,
    ),
)
