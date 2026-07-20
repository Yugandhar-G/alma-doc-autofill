"""Installed workflow packages. Installing a package = adding an entry here —
the install-as-data thesis at the code layer; engine code never changes."""
from app.kernel.package import WorkflowPackage
from app.packages.autofill.package import PACKAGE as AUTOFILL_PACKAGE
from app.packages.matter_intake.package import PACKAGE as MATTER_INTAKE_PACKAGE
from app.packages.matter_intake.planner_package import PACKAGE as MATTER_PLANNER_PACKAGE
from app.packages.preflight.package import PACKAGE as PREFLIGHT_PACKAGE
from app.screener.package import PACKAGE as SCREENER_PACKAGE

INSTALLED_PACKAGES: tuple[WorkflowPackage, ...] = (
    AUTOFILL_PACKAGE,
    PREFLIGHT_PACKAGE,
    SCREENER_PACKAGE,
    MATTER_INTAKE_PACKAGE,
    MATTER_PLANNER_PACKAGE,
)
