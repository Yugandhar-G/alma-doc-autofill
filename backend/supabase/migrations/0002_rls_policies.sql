-- Phase E2 — finalized row-level security policies (additive to 0001).
--
-- WHAT THESE PROTECT
-- The backend talks to Supabase with the SERVICE-ROLE key, which bypasses RLS
-- by design — tenancy for the backend is enforced in app/kernel/store/*.py,
-- where every query is filtered by scope.firm_id (the structural wall). These
-- policies therefore protect the OTHER client: the anon/authenticated Supabase
-- client used by the frontend via @supabase/ssr, which authenticates as the
-- signed-in firm user and MUST be boxed into that user's firm. Defense in
-- depth — if a query ever runs under the user's own JWT instead of the service
-- key, the database still refuses cross-firm rows.
--
-- CLAIM / JWT SHAPE ASSUMED
-- The app does NOT put firm_id in the JWT. Mirroring app/kernel/auth.py
-- (resolve_principal): the GoTrue access token carries `sub` (the auth-provider
-- subject); the app maps it to a firm member via public.users.auth_provider_id.
-- Supabase surfaces that subject as auth.uid(). So the caller's firm is:
--       select firm_id from public.users where auth_provider_id = auth.uid()::text
-- (ids are text in this schema; auth.uid() is a uuid, hence ::text). If a
-- deployment later mints a custom `firm_id` JWT claim, current_firm_id() can be
-- swapped to `auth.jwt() ->> 'firm_id'` for one fewer join — the policies below
-- would not otherwise change.
--
-- Idempotent: helper is create-or-replace; every policy is dropped-if-exists
-- then created, so re-applying the migration is safe.

-- Resolve the caller's firm WITHOUT tripping RLS on public.users itself. A
-- policy on users that queried users would recurse; a SECURITY DEFINER function
-- runs as the owner (RLS-exempt) and breaks that cycle. STABLE so the planner
-- may cache it per-statement. search_path pinned to defeat search-path hijack.
create or replace function public.current_firm_id()
returns text
language sql
stable
security definer
set search_path = public
as $$
    select firm_id from public.users where auth_provider_id = auth.uid()::text limit 1;
$$;

-- 1) firms — a caller sees only their own firm row.
drop policy if exists firm_isolation_firms on public.firms;
create policy firm_isolation_firms on public.firms
    for all
    using (id = public.current_firm_id())
    with check (id = public.current_firm_id());

-- 2) users — a caller sees only members of their own firm.
drop policy if exists firm_isolation_users on public.users;
create policy firm_isolation_users on public.users
    for all
    using (firm_id = public.current_firm_id())
    with check (firm_id = public.current_firm_id());

-- 3) matters
drop policy if exists firm_isolation_matters on public.matters;
create policy firm_isolation_matters on public.matters
    for all
    using (firm_id = public.current_firm_id())
    with check (firm_id = public.current_firm_id());

-- 4) matter_documents
drop policy if exists firm_isolation_matter_documents on public.matter_documents;
create policy firm_isolation_matter_documents on public.matter_documents
    for all
    using (firm_id = public.current_firm_id())
    with check (firm_id = public.current_firm_id());

-- 5) workflow_runs
drop policy if exists firm_isolation_workflow_runs on public.workflow_runs;
create policy firm_isolation_workflow_runs on public.workflow_runs
    for all
    using (firm_id = public.current_firm_id())
    with check (firm_id = public.current_firm_id());

-- 6) run_artifacts
drop policy if exists firm_isolation_run_artifacts on public.run_artifacts;
create policy firm_isolation_run_artifacts on public.run_artifacts
    for all
    using (firm_id = public.current_firm_id())
    with check (firm_id = public.current_firm_id());

-- 7) interrupts
drop policy if exists firm_isolation_interrupts on public.interrupts;
create policy firm_isolation_interrupts on public.interrupts
    for all
    using (firm_id = public.current_firm_id())
    with check (firm_id = public.current_firm_id());

-- 8) memory_records
drop policy if exists firm_isolation_memory_records on public.memory_records;
create policy firm_isolation_memory_records on public.memory_records
    for all
    using (firm_id = public.current_firm_id())
    with check (firm_id = public.current_firm_id());
