"""Kernel tool layer — the drivers agents are granted access to.

Every tool follows the driver contract: allow-list + budget + deterministic
post-audit. The registry is the allow-list mechanism: an agent can only
dispatch tools its package was granted, and an unknown name returns
UNKNOWN_TOOL instead of executing anything.
"""
from app.kernel.tools.registry import ToolContext, ToolRegistry, ToolSpec  # noqa: F401
