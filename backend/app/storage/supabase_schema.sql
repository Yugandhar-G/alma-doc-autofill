-- One-time Supabase setup for yunaki-doc-autofill.
-- Run in the Supabase SQL editor (or via supabase db push) before setting
-- SUPABASE_URL / SUPABASE_SERVICE_KEY in backend/.env.

-- 1) Extraction results table. doc_id is the SHA-256 of the uploaded bytes
--    (content-addressed, PII-safe reference). Original filenames are never stored.
-- Keyed by (doc_id, doc_type, kind): identical bytes uploaded into two slots
-- must not clobber each other, and both the raw extraction and the reviewed
-- "final" record (post-merge/coherence — what the user actually saw) coexist.
create table if not exists public.extractions (
    doc_id     text not null check (doc_id ~ '^[0-9a-f]{64}$'),
    doc_type   text not null check (doc_type in ('passport', 'g28')),
    kind       text not null default 'raw' check (kind in ('raw', 'final')),
    envelope   jsonb not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (doc_id, doc_type, kind)
);

create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end $$;

drop trigger if exists extractions_touch_updated_at on public.extractions;
create trigger extractions_touch_updated_at
    before update on public.extractions
    for each row execute function public.touch_updated_at();

-- Extracted data contains PII: lock the table down. The backend uses the
-- service-role key, which bypasses RLS; nothing else gets access.
alter table public.extractions enable row level security;

-- 2) Private storage bucket for the original documents
--    (paths: {doc_type}/{doc_id}.{pdf|png|jpg}).
insert into storage.buckets (id, name, public)
values ('documents', 'documents', false)
on conflict (id) do nothing;

-- No storage.objects policies are created: the bucket is private and only the
-- service-role key (RLS-exempt) reads or writes it.
