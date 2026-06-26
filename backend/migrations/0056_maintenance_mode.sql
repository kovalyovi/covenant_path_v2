-- Owner-only MAINTENANCE mode (2026-06-25). A single global switch the OWNER can flip so that, if
-- anyone ever sees data they shouldn't, the whole app locks down to everyone EXCEPT the owner while
-- the issue is fixed. Enforced at the RLS layer (a RESTRICTIVE policy AND'd onto the member-data
-- tables) so it contains the leak across EVERY client — web AND native — with no per-client code; the
-- clients additionally render a friendly maintenance screen. Owner-gated, NOT all admins ("protected
-- to only me"). Additive + idempotent; a no-op for normal reads while the switch is OFF (the default).

create table if not exists app_settings (
    id                  boolean primary key default true check (id),  -- single-row table
    maintenance_mode    boolean not null default false,
    maintenance_message text,
    owner_email         text,
    updated_at          timestamptz default now(),
    updated_by          text
);

-- Seed the single row + the owner email: prefer the app.owner_email GUC (injected by backend.apply
-- from OWNER_EMAIL), falling back to the bootstrap admin (app_admins, invited_by='system'). Never
-- overwrites an owner already on file.
insert into app_settings (id, owner_email)
values (true, coalesce(
    lower(btrim(nullif(current_setting('app.owner_email', true), ''))),
    (select email from app_admins where invited_by_email = 'system' order by created_at limit 1)))
on conflict (id) do update set owner_email = coalesce(app_settings.owner_email, excluded.owner_email);

alter table app_settings enable row level security;
grant select, update on app_settings to service_role;       -- broker/ops; clients use the view + RPCs
-- The table itself is NOT granted to anon/authenticated, so owner_email stays private. Clients read the
-- flag through the maintenance_status view (below) and learn owner-ness through is_owner().

-- is_owner(): is the request's verified email the single OWNER on file? (NOT is_admin — maintenance is
-- gated to the owner alone.) SECURITY DEFINER so it reads app_settings regardless of caller grants.
create or replace function is_owner() returns boolean language sql stable
security definer set search_path = public as
$$ select exists (select 1 from app_settings s
                  where s.id and s.owner_email is not null and s.owner_email = _jwt_email()) $$;
grant execute on function is_owner() to anon, authenticated;

-- maintenance_on(): the global flag, false when unset/missing. STABLE + SECURITY DEFINER so RLS
-- policies can call it cheaply.
create or replace function maintenance_on() returns boolean language sql stable
security definer set search_path = public as
$$ select coalesce((select maintenance_mode from app_settings where id), false) $$;
grant execute on function maintenance_on() to anon, authenticated;

-- Client-readable status: ONLY the public flag + message (never owner_email). Runs with definer rights
-- so clients don't need a grant on app_settings itself.
create or replace view maintenance_status as
    select maintenance_mode, maintenance_message from app_settings where id;
grant select on maintenance_status to anon, authenticated;

-- The owner-only toggle. Idempotent; records who/when. Returns the new state.
create or replace function set_maintenance_mode(p_on boolean, p_message text default null)
returns boolean language plpgsql security definer set search_path = public as $$
begin
    if not is_owner() then raise exception 'not authorized — maintenance mode is owner-only'; end if;
    update app_settings set maintenance_mode = coalesce(p_on, false),
        maintenance_message = p_message, updated_at = now(), updated_by = _jwt_email() where id;
    return coalesce(p_on, false);
end; $$;
grant execute on function set_maintenance_mode(boolean, text) to authenticated;

-- CONTAINMENT: while maintenance is ON, only the owner may read member data. A RESTRICTIVE policy is
-- AND'd onto the existing permissive RLS (it does NOT replace the role-scoping policy) — so a non-owner
-- sees ZERO members / manual_members during maintenance, on every client, while the owner keeps their
-- normal scope to investigate. When the switch is OFF, `not maintenance_on()` is true so the gate is a
-- no-op. (Stake/unit NAMES aren't member data, so they stay readable — the maintenance SCREEN handles UX.)
drop policy if exists members_maintenance_gate on members;
create policy members_maintenance_gate on members as restrictive for select
    using (not maintenance_on() or is_owner());

drop policy if exists manual_members_maintenance_gate on manual_members;
create policy manual_members_maintenance_gate on manual_members as restrictive for select
    using (not maintenance_on() or is_owner());
