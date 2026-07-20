"""Fan-out prompts — one per artifact family. Each authoring agent gets the
brief plus these instructions, is granted only read_exemplar + write_candidate,
and is told to STUDY the preflight exemplar before writing anything.

The candidate package layout mirrors app/packages/preflight/ exactly, so a
passing candidate is a human add-one-line-to-registry away from installed:

    app/packages/_candidates/<candidate_id>/
        __init__.py
        schemas.py        (schemas family)
        state.py          (graph family)
        knowledge/        (knowledge family)
        graph.py          (graph family)
        package.py        (graph family — exports PACKAGE)
        eval.py           (eval family — exports build_harness)
"""
from __future__ import annotations

_SHARED_HEADER = """You are authoring ONE artifact family of a new Yunaki vertical package.

You may ONLY use two tools:
- read_exemplar(path): study shipped source. START by reading the preflight
  exemplar files relevant to your family (e.g. app/packages/preflight/schemas.py,
  app/packages/preflight/graph.py, app/packages/preflight/package.py) and, for
  the package contract, app/kernel/package.py. Read before you write.
- write_candidate(relpath, content): write a file into THIS candidate package.
  Paths are relative to the candidate package root. You cannot write anywhere
  else; absolute paths and '..' are refused.

Use ABSOLUTE imports rooted at `app.packages._candidates.{candidate_id}` (the
exemplar uses `app.packages.preflight...`; yours mirrors that). Keep every file
under 800 lines. Every schema field Optional-with-default where the extraction
contract applies. No secrets, no network, no LLM calls in graph nodes unless the
brief demands it and the exemplar shows how.

The package id for the manifest MUST be exactly: {candidate_id}

--- BRIEF ---
{brief}
--- END BRIEF ---
"""

_FAMILIES = {
    "knowledge": """
YOUR FAMILY: knowledge registries.
Study app/packages/preflight/knowledge/ (requirements.py, form_editions.py).
Write the domain knowledge this package needs as DATA (registries, tables,
lookups) under 'knowledge/'. Include 'knowledge/__init__.py'. Knowledge is
checked-in reference data validated on load — never runtime state, never guessed
values. Write only the files your family owns.
""",
    "schemas": """
YOUR FAMILY: schemas.
Study app/packages/preflight/schemas.py. Write 'schemas.py' — the package's
Pydantic report/finding contracts. They double as Gemini response_schemas, so
they MUST be flat and Gemini-safe: NO discriminated unions, NO maxItems/max_length
on any list-of-model field (caps on list[str] are fine), every model serializes
via model_json_schema(). Write only 'schemas.py'.
""",
    "graph": """
YOUR FAMILY: graph + package export.
Study app/packages/preflight/state.py, graph.py, package.py, and
app/kernel/package.py (the WorkflowPackage/PackageManifest contract).
Write:
- 'state.py' — the graph state (a pydantic BaseModel).
- 'graph.py' — a deterministic StateGraph with fixed edges and a build_graph(
  checkpointer=None) that compiles it. Routing by pure functions only; the LLM
  never picks the path.
- 'package.py' — exports `PACKAGE = WorkflowPackage(...)` wiring the manifest,
  state_model, build_graph, and eval_kit=build_harness (import it from your
  eval module). The manifest package_id MUST equal the candidate id.
- '__init__.py' — empty package marker.
""",
    "eval": """
YOUR FAMILY: eval personas + harness.
Study app/packages/preflight/eval/personas.py and eval/run.py, and
app/kernel/evalkit/harness.py (the Harness contract).
Write 'eval.py' exporting a zero-arg `build_harness()` that returns a kernel
`Harness`: synthetic personas (fully offline, no LLM, no network), an async
run_one, classes_of, render, gate, and a `worst_class` naming this package's
unforgivable defect. A clean/bait persona MUST produce zero defects. The eval
must exit 0 offline. Write only 'eval.py'.
""",
}

# Deterministic order: knowledge and schemas first (graph imports them), eval
# before graph is fine (graph only needs the symbol name at import of package.py
# — but the exemplar-faithful order below builds foundations first).
FAMILY_ORDER: tuple[str, ...] = ("knowledge", "schemas", "eval", "graph")


def family_prompt(family: str, *, brief: str, candidate_id: str) -> str:
    if family not in _FAMILIES:
        raise KeyError(f"unknown artifact family: {family!r}")
    header = _SHARED_HEADER.format(candidate_id=candidate_id, brief=brief)
    return header + _FAMILIES[family].format(candidate_id=candidate_id)
