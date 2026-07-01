"""Playwright fill routine — implemented by Agent B per the interface
contract in __init__.py. This stub keeps the API importable until then."""
from app.schemas import G28Data, PassportData, PopulationReport


async def populate_form(
    passport: PassportData | None,
    g28: G28Data | None,
    headed: bool | None = None,
) -> PopulationReport:
    raise NotImplementedError("population engine not implemented yet (Agent B)")
