-- Matter store — firm-scoped data layer for the Yunaki OS firm-sync plane.
-- Additive-only. Apply via `supabase db push` (or the SQL editor) before
-- setting SUPABASE_URL / SUPABASE_SERVICE_KEY in backend/.env.
--
-- The backend uses the service-role key (RLS-exempt); until the Phase E2
-- policy audit, the tenancy wall is enforced in app/kernel/store/*.py, which
-- filters every query by firm_id. RLS is ENABLED below with firm-scoped policy
-- TEMPLATES commented out — they are finalized and audited in Phase E2, when
-- the anon/authenticated client paths land. Do not treat these as final.

-- 1) Firms (tenants) --------------------------------------------------------
create table if not exists public.firms (
    id         text primary key,
    name       text not null,
    created_at timestamptz not null default now()
);

-- 2) Users ------------------------------------------------------------------
create table if not exists public.users (
    id               text primary key,
    firm_id          text not null references public.firms (id),
    email            text not null,
    role             text not null check (role in ('attorney', 'staff', 'admin')),
    auth_provider_id text,
    created_at       timestamptz not null default now()
);
create index if not exists idx_users_firm on public.users (firm_id);
create index if not exists idx_users_auth on public.users (auth_provider_id);

-- 3) Matters ----------------------------------------------------------------
create table if not exists public.matters (
    id          text primary key,
    firm_id     text not null references public.firms (id),
    matter_type text not null,
    title       text not null,
    client_ref  text,
    status      text not null check (status in ('open', 'closed')),
    created_by  text not null,
    created_at  timestamptz not null default now()
);
create index if not exists idx_matters_firm on public.matters (firm_id);

-- 4) Matter documents (pointers into DocumentStore; doc_id is the content hash)
create table if not exists public.matter_documents (
    id          text primary key,
    matter_id   text not null references public.matters (id),
    firm_id     text not null references public.firms (id),
    doc_id      text not null,
    doc_type    text not null,
    filename    text not null,
    uploaded_by text not null,
    created_at  timestamptz not null default now()
);
create index if not exists idx_docs_matter on public.matter_documents (matter_id);
create index if not exists idx_docs_firm on public.matter_documents (firm_id);

-- 5) Workflow runs ----------------------------------------------------------
create table if not exists public.workflow_runs (
    id           text primary key,
    matter_id    text not null references public.matters (id),
    firm_id      text not null references public.firms (id),
    package_id   text not null,
    status       text not null check (status in ('queued', 'running', 'awaiting_input', 'done', 'error')),
    thread_id    text not null,
    started_by   text not null,
    created_at   timestamptz not null default now(),
    finished_at  timestamptz,
    summary_json jsonb not null default '{}'::jsonb
);
create index if not exists idx_runs_matter on public.workflow_runs (matter_id);
create index if not exists idx_runs_firm on public.workflow_runs (firm_id);
create index if not exists idx_runs_firm_status on public.workflow_runs (firm_id, status);

-- 6) Run artifacts ----------------------------------------------------------
create table if not exists public.run_artifacts (
    id           text primary key,
    run_id       text not null references public.workflow_runs (id),
    firm_id      text not null references public.firms (id),
    kind         text not null check (kind in ('report', 'population_pdf', 'population_png', 'transcript')),
    artifact_ref text not null,
    created_at   timestamptz not null default now()
);
create index if not exists idx_artifacts_run on public.run_artifacts (run_id);
create index if not exists idx_artifacts_firm on public.run_artifacts (firm_id);

-- 7) Interrupts (HITL queue) ------------------------------------------------
create table if not exists public.interrupts (
    id           text primary key,
    run_id       text not null references public.workflow_runs (id),
    firm_id      text not null references public.firms (id),
    kind         text not null,
    node         text not null,
    payload_json jsonb not null default '{}'::jsonb,
    status       text not null check (status in ('pending', 'resolved', 'expired')),
    created_at   timestamptz not null default now(),
    resolved_by  text,
    resolved_at  timestamptz
);
create index if not exists idx_interrupts_firm on public.interrupts (firm_id);
create index if not exists idx_interrupts_firm_status on public.interrupts (firm_id, status);

-- 8) Memory records (firm memory; writers land in D1) -----------------------
create table if not exists public.memory_records (
    id            text primary key,
    firm_id       text not null references public.firms (id),
    matter_id     text not null references public.matters (id),
    run_id        text,
    matter_type   text not null,
    kind          text not null check (kind in ('rfe', 'denial', 'approval', 'review_edit', 'outcome_note')),
    criterion_key text,
    summary       text not null,
    detail_json   jsonb not null default '{}'::jsonb,
    created_at    timestamptz not null default now()
);
create index if not exists idx_memory_firm on public.memory_records (firm_id);
create index if not exists idx_memory_matter on public.memory_records (matter_id);
create index if not exists idx_memory_firm_type on public.memory_records (firm_id, matter_type);

-- Row-level security -------------------------------------------------------
-- Enable RLS on every firm-scoped table. The service-role key bypasses RLS,
-- so the backend keeps working today; these tables are simply locked to
-- everything else until the E2 policies below are finalized.
alter table public.firms enable row level security;
alter table public.users enable row level security;
alter table public.matters enable row level security;
alter table public.matter_documents enable row level security;
alter table public.workflow_runs enable row level security;
alter table public.run_artifacts enable row level security;
alter table public.interrupts enable row level security;
alter table public.memory_records enable row level security;

-- === Phase E2 policy TEMPLATES (NOT FINAL — audited/enabled in E2) =========
-- These assume the authenticated client carries the caller's firm_id (e.g. as
-- a JWT claim surfaced via auth.jwt() ->> 'firm_id', or resolved from a
-- users-table join on auth.uid()). The exact claim wiring is an E2 decision;
-- do not uncomment until that path exists and is reviewed.
--
-- create policy firm_isolation_matters on public.matters
--     for all
--     using (firm_id = (auth.jwt() ->> 'firm_id'))
--     with check (firm_id = (auth.jwt() ->> 'firm_id'));
--
-- Repeat the same firm_id-equality using/with-check pair for users,
-- matter_documents, workflow_runs, run_artifacts, interrupts, and
-- memory_records. firms itself is scoped by membership (id in the caller's
-- firm), which E2 resolves once the auth→firm mapping is finalized.
