"""The matter API surface — the firm-facing HTTP layer over the matter store,
auth, and the workflow runtime (Phase C1c).

Additive to the legacy session endpoints in app.main and the per-package
routers: this is the matter-centric path (matters → documents → runs → inbox)
the OS shell drives. Everything here sits behind get_principal and is filtered
by the resolved TenantScope inside the store — a router cannot express a
cross-firm read.
"""
from app.api.matters import router  # noqa: F401

__all__ = ["router"]
