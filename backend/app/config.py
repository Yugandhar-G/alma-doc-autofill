"""Compatibility shim — configuration moved to app.kernel.config (Phase 1 of
the OS build). Import from app.kernel.config in new code; this module keeps
the old import path working (same function object, so lru_cache clearing and
monkeypatching behave identically).
"""
from app.kernel.config import Settings, SettingsBundle, get_settings  # noqa: F401
