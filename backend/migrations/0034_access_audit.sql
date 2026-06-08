-- Access-visibility logging: a persistent, admin-only trail answering "who can see what, and what
-- changed" — the two failure modes that matter for a privacy-sensitive app:
--   • UNDER-visibility: a leader who should see their stake/ward sees nothing.
--   • OVER-visibility:  someone sees data they shouldn't.
-- Two parts:
--   1) access_audit — every role GRANT/REVOKE from provision_roles (who gained/lost member-data
--      access, their calling + scope). The trail to spot wrong/lost access.
--   2) login_audit.role_scope — what a sign-in ACTUALLY resolves to (their user_roles). An
--      'allowed' login with role_scope='none' = logged in but sees an empty app (under-visibility);
--      a scope naming an unexpected stake = over-visibility.
-- Privacy-sensitive (holds emails/callings) → admin-only via RLS. Additive + idempotent.

create table if not exists access_audit (
    id          bigint generated always as identity primary key,
    at          timestamptz not null default now(),
    stake_id    uuid,
    stake_unit  integer,
    action      text,          -- 'granted' | 'revoked'
    role        text,          -- 'stake_leader' | 'ward_leader'
    unit_id     uuid,          -- the ward (ward_leader) or NULL (stake-wide)
    person_uuid text,
    name        text,
    email       text,
    calling     text,
    source      text           -- 'provision' | 'power_user' | 'manual'
);

alter table access_audit enable row level security;
grant select on access_audit to anon, authenticated;          -- RLS policy below restricts to admins
grant insert, select on access_audit to service_role;          -- broker/sync may write
drop policy if exists access_audit_select on access_audit;
create policy access_audit_select on access_audit for select using (is_admin());
create index if not exists access_audit_at_idx on access_audit (at desc);

-- What a login actually resolves to (their user_roles scope), appended to the login audit so an
-- 'allowed' sign-in that sees nothing (role_scope='none') is visible.
alter table login_audit add column if not exists role_scope text;
