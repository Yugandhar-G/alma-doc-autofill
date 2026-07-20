"""evalkit — the kernel's shared eval harness.

Package-agnostic by the kernel contract: nothing here imports from
app.screener, app.extraction, app.population, or validation. The validation
runners are thin configs over ``Harness``; see harness.py for the invariants
the kernel enforces (worst-class exit gate, per-item isolation).
"""
from app.kernel.evalkit.harness import HARNESS_ERROR_KEY, Harness, Result, retry_async

__all__ = ["HARNESS_ERROR_KEY", "Harness", "Result", "retry_async"]
