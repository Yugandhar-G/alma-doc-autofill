# Module names deliberately differ from the exported functions (verdicts.py →
# verdict) so package attributes never shadow submodules on attribute traversal.
from .assess import assess_one
from .compile import compile_matrix
from .exhibit_index import exhibit_index
from .merits import final_merits
from .report import assemble_report
from .review import review_gate
from .summary import profile_summary
from .verdicts import verdict
from .verify import verify_profile

__all__ = [
    "assess_one",
    "assemble_report",
    "compile_matrix",
    "exhibit_index",
    "final_merits",
    "profile_summary",
    "review_gate",
    "verdict",
    "verify_profile",
]
