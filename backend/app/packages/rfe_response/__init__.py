"""RFE response assembler package (Phase D3).

Parse a USCIS Request-for-Evidence notice → extract the deadline and the grounds
→ produce a cited response checklist + a code-assembled cover structure → human
review → feed the outcome to firm memory (kind="rfe") so future Pre-Flight runs
recall the firm's RFE patterns.

Vision + one distillation call per run; everything else is deterministic and
replayable (deadline math takes ``today`` from state, never datetime.now()).
"""
