"""Matter-intake package — three firm-data deep agents that reason over the
firm's OWN records (no web, ever):

- chase  (package ``matter_intake``): classify document arrivals, reason about
  gaps against the case-type requirements registry, draft client chase
  messages, human-review, record the outcome to firm memory.
- planner (package ``matter_planner``): investigate the matter, propose which
  installed workflows to run next, human-review, queue the approved runs.
- ask     (rides matter_intake's router): a sync research endpoint that answers
  a question strictly from firm data, refs audited against the transcript.

Shared discipline (mirrors the screener agent): deepagents owns the loop, CODE
owns the grants (a firm-data subset of CORPUS_TOOLS — NO web tools), the budget,
and the transcript audit. A claim citing a ref the agent never saw
(transcript.seen_refs) is stripped; a "missing document" claim for a document
that EXISTS is the fabrication class and is dropped with a warning.
"""
