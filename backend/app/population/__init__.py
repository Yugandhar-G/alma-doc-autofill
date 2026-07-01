"""Population plane public interface.

Contract (implemented in fill.py — Agent B):

    async def populate_form(
        passport: PassportData | None,
        g28: G28Data | None,
        headed: bool | None = None,   # None → settings.populate_headed
    ) -> PopulationReport

Rules: iterate FIELD_MAP only; fill()/select_option()/check() only;
skip nulls; after filling, read every touched control back and diff
(verify.py) → PopulationReport. Navigation locked to
settings.target_form_url; hard timeout settings.populate_timeout_ms.
"""
from .fill import populate_form

__all__ = ["populate_form"]
