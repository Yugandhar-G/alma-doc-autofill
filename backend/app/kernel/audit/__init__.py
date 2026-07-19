"""Kernel audit subsystem — deterministic checks that can overrule LLM output.

No LLM runs anywhere in this package. The kernel provides the machinery
(ref stripping, transcript-evidence auditing); each workflow package owns its
policy (which verdicts downgrade to what). The invariant across all of it:
an uncited positive claim never ships — a null is correct, a plausible guess
is a defect.
"""
from app.kernel.audit.refs import audit_refs, normalize  # noqa: F401
from app.kernel.audit.transcript import audit_evidence_urls  # noqa: F401
