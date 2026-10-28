create table if not exists public.qa_reports (
    id uuid primary key default gen_random_uuid(),
    project_ref_raw text not null,
    run_id text not null,
    report_at timestamptz not null,
    report_date date not null,
    report_time_source text not null,
    source text not null,
    bug_count integer not null default 0 check (bug_count >= 0),
    storage_path text not null,
    index_md text,
    raw jsonb not null,
    content_hash text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint qa_reports_project_run_key unique (project_ref_raw, run_id)
);

create table if not exists public.qa_bugs (
    id uuid primary key default gen_random_uuid(),
    report_id uuid not null references public.qa_reports(id) on delete cascade,
    bug_key text not null,
    external_id text not null,
    title text,
    priority text,
    status text not null default 'open',
    description text,
    steps jsonb not null default '[]'::jsonb,
    expected text,
    actual text,
    attachments jsonb not null default '[]'::jsonb,
    body_md text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint qa_bugs_report_external_key unique (report_id, external_id)
);

create index if not exists ix_qa_reports_report_date
    on public.qa_reports (report_date desc);

create index if not exists ix_qa_bugs_bug_key
    on public.qa_bugs (bug_key);

create index if not exists ix_qa_bugs_status
    on public.qa_bugs (status);
