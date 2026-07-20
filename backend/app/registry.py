"""Installed workflow packages. Installing a package = adding an entry here —
the install-as-data thesis at the code layer; engine code never changes."""
from app.kernel.package import WorkflowPackage
from app.packages.autofill.package import PACKAGE as AUTOFILL_PACKAGE
from app.screener.package import PACKAGE as SCREENER_PACKAGE

INSTALLED_PACKAGES: tuple[WorkflowPackage, ...] = (
    AUTOFILL_PACKAGE,
    SCREENER_PACKAGE,
)
