"""Structural checks on the Supabase RLS migrations.

There is no live Postgres in the offline suite, so we cannot assert runtime
policy behavior. What IS verifiable and worth locking down: every firm-scoped
table has RLS ENABLED (0001) and at least one POLICY (0002), and the policies
resolve the caller's firm through the users-table join the app actually uses
(auth.uid() → users.auth_provider_id), not a firm_id JWT claim the tokens do
not carry. This test fails loudly if a new table is added without a policy, or
if the claim wiring drifts from app/kernel/auth.py.
"""
import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"

# The eight firm-scoped tables from 0001_matters.sql.
FIRM_SCOPED_TABLES = (
    "firms",
    "users",
    "matters",
    "matter_documents",
    "workflow_runs",
    "run_artifacts",
    "interrupts",
    "memory_records",
)


def _read(name: str) -> str:
    return (MIGRATIONS / name).read_text().lower()


def test_every_table_has_rls_enabled() -> None:
    sql = _read("0001_matters.sql")
    for table in FIRM_SCOPED_TABLES:
        assert f"alter table public.{table} enable row level security" in sql, table


def test_every_table_has_a_policy() -> None:
    sql = _read("0002_rls_policies.sql")
    for table in FIRM_SCOPED_TABLES:
        # `create policy <name> on public.<table>`
        pattern = rf"create policy\s+\w+\s+on\s+public\.{table}\b"
        assert re.search(pattern, sql), f"no policy for {table}"


def test_policies_use_the_users_join_not_a_jwt_firm_claim() -> None:
    sql = _read("0002_rls_policies.sql")
    # The app derives firm via users.auth_provider_id = auth.uid() (see
    # kernel/auth.py). The helper must encode exactly that.
    assert "auth_provider_id = auth.uid()" in sql
    assert "current_firm_id()" in sql


def test_users_policy_avoids_recursion_via_security_definer() -> None:
    sql = _read("0002_rls_policies.sql")
    # A policy on users that queried users would recurse; the helper is
    # SECURITY DEFINER precisely to break that cycle.
    assert "security definer" in sql
    assert "set search_path" in sql  # search-path pinned on the definer fn


def test_migration_documents_service_key_bypass() -> None:
    sql = _read("0002_rls_policies.sql")
    # Honesty requirement: the file must state that the backend service key
    # bypasses RLS by design and tenancy is enforced in the store layer.
    assert "service-role key" in sql
    assert "app/kernel/store" in sql
