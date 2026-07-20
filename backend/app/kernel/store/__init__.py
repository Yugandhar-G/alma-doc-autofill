"""Matter store — the firm-scoped data layer (matters, documents, runs,
artifacts, interrupts, memory) every C/D-tier workflow builds on. SQLite for
local no-account mode; Supabase for the firm-sync plane. Public surface:
the models, the TenantScope + MatterStore contract, and the factory."""
from app.kernel.store.base import (
    MatterStore,
    TenantScope,
    get_matter_store,
    thread_id_for,
)

__all__ = ["MatterStore", "TenantScope", "get_matter_store", "thread_id_for"]
