"""Demo agent layer — real bounded tool-loops on the yunaki kernel engine.

The email brain (and any future demo agent) is a REAL agent: a bounded
tool-loop where the MODEL decides what to look up and when it is ready to act.
The loop itself is the yunaki kernel's deepagents-backed engine
(app.kernel.agent.run_tool_loop) — this package does NOT hand-roll a loop and
does NOT call an LLM provider directly. deepagents owns the loop; code owns the
grants (ToolRegistry allow-list), the budget, and the transcript.

  harness.py     — builds ToolContext + AgentTranscript, runs run_tool_loop with
                   the code-owned AgentBudget, and persists the full transcript.
  tools_case.py  — shared read-only tools over the /core case tables.

Kernel symbols are imported lazily (inside functions / behind seams) so the rest
of the demo imports on any interpreter; the kernel agent engine itself needs the
yunaki backend (Python >=3.11, deepagents + langchain-google-genai on Gemini).
"""
