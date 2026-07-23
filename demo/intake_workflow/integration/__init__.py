"""Native integration between the intake workflow app and the shared /core system.

This package is the seam between the intake app (``intake_workflow.*``) and our
shared contracts (the ``core`` package + the single monorepo SQLite database).

The integration is NATIVE in the monorepo — there is no opt-in switch. The old
``YUNAKI_SHARED_DB`` env var is gone; ``config.enabled()`` returns True
unconditionally and ``config.shared_conn()`` connects to ``core.config.get_db_path()``
(the one database every plane shares).

Design invariants (see docs/integration-bridge.md):
  - Integration files import ``core.*`` LAZILY, inside functions, to stay
    import-cheap and free of import-ordering coupling to /core.
  - Integration files do not import ``intake_workflow.*`` except at the documented
    seams (they receive the store / timeline events as arguments instead).
  - The integration owns aux tables (``iw_*``) in the shared DB; it never mutates
    /core contract tables except the two documented, coordinated writes
    (drafts+events from the send gate, intake.url from the handoff consumer).
"""
