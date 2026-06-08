-- Login audit: one row per Church-login evaluation so admins can see WHO tried to sign in, the
-- stake + callings they presented, the access they were granted, and the OUTCOME (allowed /
-- blocked / undetermined / enrolled). Privacy-sensitive (holds the sign-in email) → admin-only
-- visibility via RLS; the broker writes it with the service-role key. Additive + idempotent.

create table if not exists login_audit (
    id           bigint generated always as identity primary key,
    at           timestamptz not null default now(),
    email        text,                  -- who attempted (lowercased); null if unknown
    name         text,
    stake_unit   integer,               -- their stake's unit_number
    stake_name   text,
    callings     jsonb,                 -- runner position names, e.g. ["Stake President"]
    authorized   text,                  -- 'allowed' | 'blocked' | 'undetermined'
    access_rank  integer,
    can_pull_all boolean,
    outcome      text,                  -- 'allowed' | 'blocked' | 'undetermined' | 'enrolled' | 'error'
    error        text,
    request_id   text
);

alter table login_audit enable row level security;
-- RLS needs a base grant to even evaluate the policy; the policy then restricts SELECT to admins.
grant select on login_audit to anon, authenticated;
-- the broker (service-role key over PostgREST) writes audit rows; service_role bypasses RLS.
grant insert, select on login_audit to service_role;

drop policy if exists login_audit_select on login_audit;
create policy login_audit_select on login_audit for select using (is_admin());

create index if not exists login_audit_at_idx on login_audit (at desc);
