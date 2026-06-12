-- 0048: Security hardening (audit 2026-06-11). Additive + idempotent.
--
-- Closes access-control findings from the full-stack security audit:
--   DBRLS-02 / BACKEND-10  provider-binding trigger trusted principal_email blindly
--   DBRLS-01               set_stake_sheets_enabled missing the empty-email nullif guard
--   DBRLS-03               revoke_power_user let any co-leader revoke another's invitees
--   DBRLS-04               member_comments INSERT didn't bind the person to a real member
--   DBRLS-05               remove_stake left login_audit / access_audit PII behind
--   DBRLS-06               cross-stake ward re-parents were silent
--   DBRLS-07               documented (ADR in docs/DECISIONS.md) — no DDL change here
--
-- Apply with: python -m backend.apply   (migrations are applied manually; CI applies
-- them to the TEST project via .github/workflows/tests.yml).

-- ============================================================================
-- DBRLS-02 / BACKEND-10 — bind_provider_stake_role
-- The 0029 trigger granted a STAKE-WIDE stake_leader role to ANY principal_email on
-- ANY non-revoked credential write, trusting the email outright. Two tightenings:
--   (1) HARD GATE: only an ACCESS-BEARING enrollment (access_rank + granting_role_ids
--       populated, which only the vetted enroll_stake_credential RPC sets after a real
--       LCR login) may mint a role. A bare/partial write to stake_credentials no longer
--       grants anything — closing the realistic "direct write mints stake access" vector.
--   (2) CORROBORATE the email against the broker's verified identity cache for THIS
--       stake's unit. The normal enroll writes church_identities (auth_broker/enroll.py
--       set_unit at ~L298) BEFORE the credential RPC (~L393), so a real enroll is
--       corroborated. That write is best-effort, so an UNcorroborated binding still
--       proceeds (never re-break the "enroller sees 0 members" bug 0029 fixed) but is
--       recorded in role_binding_audit for admin review/alerting.
-- ============================================================================

create table if not exists role_binding_audit (
    id              bigint generated always as identity primary key,
    at              timestamptz not null default now(),
    stake_id        uuid,
    principal_email text,
    reason          text
);
alter table role_binding_audit enable row level security;
grant select on role_binding_audit to anon, authenticated;     -- RLS policy restricts rows to admins
grant insert, select on role_binding_audit to service_role;
drop policy if exists role_binding_audit_select on role_binding_audit;
create policy role_binding_audit_select on role_binding_audit for select using (is_admin());
create index if not exists role_binding_audit_at_idx on role_binding_audit (at desc);

create or replace function bind_provider_stake_role() returns trigger
language plpgsql security definer set search_path = public as $$
declare
    v_unit_number  bigint;
    v_corroborated boolean;
begin
    -- nothing to bind for a revoked or email-less credential row
    if NEW.principal_email is null or btrim(NEW.principal_email) = ''
       or coalesce(NEW.revoked, false) <> false then
        return NEW;
    end if;

    -- (1) HARD GATE — require a real access posture (set only by the enroll RPC).
    if NEW.access_rank is null
       or NEW.granting_role_ids is null
       or array_length(NEW.granting_role_ids, 1) is null then
        return NEW;
    end if;

    -- (2) Corroborate against the verified identity cache for this stake's unit.
    select unit_number into v_unit_number from stakes where id = NEW.stake_id;
    select exists (
        select 1 from church_identities ci
        where lower(ci.email) = lower(NEW.principal_email)
          and ci.unit_number = v_unit_number
    ) into v_corroborated;

    if not v_corroborated then
        insert into role_binding_audit (stake_id, principal_email, reason)
        values (NEW.stake_id, lower(NEW.principal_email),
                'uncorroborated: no church_identities row for email+unit at bind time');
    end if;

    insert into user_roles (stake_id, unit_id, role, email, source)
    values (NEW.stake_id, null, 'stake_leader', lower(NEW.principal_email), 'enrollment')
    on conflict (stake_id, coalesce(unit_id, '00000000-0000-0000-0000-000000000000'::uuid),
                 role, coalesce(lcr_person_uuid, lower(email), ''))
    do nothing;
    return NEW;
end; $$;
-- the trigger trg_bind_provider_stake_role (0029) already targets this function.

-- ============================================================================
-- DBRLS-01 — set_stake_sheets_enabled: use the empty-email nullif guard that
-- every other policy/function uses (0004/0005/0017), so a JWT with no/empty
-- email claim can never match a stored role.
-- ============================================================================
create or replace function set_stake_sheets_enabled(p_stake_id uuid, p_enabled boolean)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
    if not exists (
        select 1 from user_roles
        where stake_id = p_stake_id
          and role = 'stake_leader'
          and (lower(email) = lower(nullif(auth.jwt() ->> 'email','')) or auth_id = auth.uid())
    ) then
        raise exception 'not authorized: only a stake leader can toggle sheet generation';
    end if;
    update stakes set sheets_enabled = p_enabled where id = p_stake_id;
    return p_enabled;
end;
$$;
revoke all on function set_stake_sheets_enabled(uuid, boolean) from public;
grant execute on function set_stake_sheets_enabled(uuid, boolean) to authenticated;

-- ============================================================================
-- DBRLS-03 — revoke_power_user: only the inviter (or an app admin) may revoke an
-- invitee, and every revoke is audited. Stops a co-leader in a shared stake from
-- revoking another leader's invited power users. (Behavior change: a stake leader
-- who did NOT issue an invite must be an admin to revoke it.)
-- ============================================================================
create table if not exists power_user_audit (
    id           bigint generated always as identity primary key,
    at           timestamptz not null default now(),
    action       text not null,            -- 'revoke'
    target_email text,
    actor_email  text,
    scopes       integer
);
alter table power_user_audit enable row level security;
grant select on power_user_audit to anon, authenticated;       -- RLS policy restricts rows to admins
grant insert, select on power_user_audit to service_role;
drop policy if exists power_user_audit_select on power_user_audit;
create policy power_user_audit_select on power_user_audit for select using (is_admin());
create index if not exists power_user_audit_at_idx on power_user_audit (at desc);

create or replace function revoke_power_user(p_email text)
returns integer language plpgsql security definer set search_path = public as $$
declare
    caller_email text    := _jwt_email();
    caller_uid   uuid    := _jwt_uid();
    caller_admin boolean := is_admin();
    n integer;
begin
    p_email := lower(btrim(p_email));
    delete from user_roles tgt
    where tgt.source = 'invitation' and lower(tgt.email) = p_email
      and (caller_admin or lower(coalesce(tgt.invited_by_email,'')) = caller_email)
      and exists (select 1 from user_roles c
                  where (c.auth_id = caller_uid or lower(c.email) = caller_email)
                    and c.stake_id = tgt.stake_id
                    and (c.unit_id is null or c.unit_id = tgt.unit_id));
    get diagnostics n = row_count;
    update invitations i set status = 'revoked', revoked_at = now()
    where lower(i.invited_email) = p_email and i.status <> 'revoked'
      and (caller_admin or lower(coalesce(i.invited_by_email,'')) = caller_email)
      and exists (select 1 from user_roles c
                  where (c.auth_id = caller_uid or lower(c.email) = caller_email)
                    and c.stake_id = i.stake_id
                    and (c.unit_id is null or c.unit_id = i.unit_id));
    insert into power_user_audit (action, target_email, actor_email, scopes)
    values ('revoke', p_email, caller_email, n);
    return n;
end; $$;
grant execute on function revoke_power_user(text) to authenticated;

-- ============================================================================
-- DBRLS-04 — member_comments INSERT must reference a member that actually lives
-- in the claimed (stake_id, unit_id), not just any person_uuid under a stake the
-- author leads.
-- ============================================================================
drop policy if exists member_comments_insert on member_comments;
create policy member_comments_insert on member_comments for insert with check (
  lower(author_email) = lower(nullif(auth.jwt() ->> 'email',''))
  and exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email','')))
      and ur.stake_id = member_comments.stake_id
      and (ur.unit_id is null or ur.unit_id = member_comments.unit_id))
  and exists (select 1 from members m
    where m.person_uuid = member_comments.member_person_uuid
      and m.stake_id = member_comments.stake_id
      and (member_comments.unit_id is null or m.unit_id = member_comments.unit_id)));

-- ============================================================================
-- DBRLS-05 — remove_stake also scrubs the admin audit tables, honoring its
-- documented "as if it never onboarded" guarantee. access_audit keys by stake_id;
-- login_audit by the stake's unit_number.
-- ============================================================================
create or replace function remove_stake(p_stake_id uuid) returns void
language plpgsql security definer set search_path = public as $$
declare v_unit bigint;
begin
    select unit_number into v_unit from stakes where id = p_stake_id;
    -- explicit child deletes first (don't rely on a particular FK on-delete config), then the row.
    delete from stake_credentials where stake_id = p_stake_id;
    delete from members           where stake_id = p_stake_id;
    delete from user_roles        where stake_id = p_stake_id;
    delete from sync_diagnostics  where stake_id = p_stake_id;
    delete from access_audit      where stake_id = p_stake_id;
    if v_unit is not null then
        delete from login_audit   where stake_unit = v_unit;
    end if;
    delete from stakes            where id = p_stake_id;
end; $$;
revoke all on function remove_stake(uuid) from public;
grant execute on function remove_stake(uuid) to service_role;

-- ============================================================================
-- DBRLS-06 — make cross-stake ward re-parents observable. units.unit_number is
-- globally unique by LCR design and db.upsert_unit re-parents a moved ward via
-- ON CONFLICT (unit_number) ... SET stake_id; log moves so a restructuring flap
-- is visible instead of silent. (Defensive logging only — behavior unchanged.)
-- ============================================================================
create table if not exists unit_reparent_audit (
    id          bigint generated always as identity primary key,
    at          timestamptz not null default now(),
    unit_number bigint,
    from_stake  uuid,
    to_stake    uuid
);
alter table unit_reparent_audit enable row level security;
grant select on unit_reparent_audit to anon, authenticated;
grant insert, select on unit_reparent_audit to service_role;
drop policy if exists unit_reparent_audit_select on unit_reparent_audit;
create policy unit_reparent_audit_select on unit_reparent_audit for select using (is_admin());

create or replace function log_unit_reparent() returns trigger
language plpgsql security definer set search_path = public as $$
begin
    if NEW.stake_id is distinct from OLD.stake_id then
        insert into unit_reparent_audit (unit_number, from_stake, to_stake)
        values (NEW.unit_number, OLD.stake_id, NEW.stake_id);
    end if;
    return NEW;
end; $$;
drop trigger if exists trg_log_unit_reparent on units;
create trigger trg_log_unit_reparent after update on units
    for each row execute function log_unit_reparent();

-- Make PostgREST pick up the new audit tables immediately.
notify pgrst, 'reload schema';
