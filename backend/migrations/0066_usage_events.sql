-- 0066: how often the tool is actually used, by unit and by calling -- with no names in it.
--
-- We could not answer "who is getting value out of this?" at all. `login_audit` (0033) looked like
-- the answer but is not: it records SIGN-INS, and only some of them. A browser email-OTP login goes
-- straight to Supabase without touching the broker, so it is never audited; the relay rows that do
-- exist carry no unit and no calling (email_relay._audit_relay_login writes email + outcome only);
-- and a signed-in session lasts for days, so sign-ins undercount use by a wide, unknowable margin.
--
-- So record USE instead: one row the first time a person opens the app on a given day on a given
-- surface. That is the honest unit for "how often" -- days-used, per unit, per calling.
--
-- PRIVACY -- the point of this table. It holds NO email, NO name, NO person uuid. The caller does
-- not supply the dimensions either: `record_app_open` is SECURITY DEFINER and derives unit, stake,
-- calling and role from the caller's OWN user_roles row, so a client cannot inflate or misattribute
-- anything. Identity survives only as `person_key`, a salted one-way hash, which exists purely so
-- "12 opens" can be told apart from "12 different people" -- it is never selected by any view and
-- cannot be reversed to an email. That means this table, unlike login_audit, does not have to be
-- admin-only to be safe; the aggregate function is admin-gated anyway.
--
-- Additive + idempotent.

create table if not exists usage_events (
    id          bigint generated always as identity primary key,
    at          timestamptz not null default now(),
    day         date        not null default ((now() at time zone 'utc')::date),
    person_key  text        not null,   -- salted one-way hash; pseudonymous, never displayed
    surface     text        not null,   -- 'web' | 'ios' | 'android'
    stake_id    uuid        references stakes(id) on delete set null,
    stake_name  text,
    unit_number bigint,
    unit_name   text,
    calling     text,                   -- user_roles.calling_name at the time of use
    role        text                    -- 'stake_leader' | 'ward_leader' | 'admin'
);

-- One row per person per surface per day: makes a row mean "used it that day" and bounds growth to
-- (people x surfaces) per day no matter how often the app is reopened.
create unique index if not exists usage_events_person_day_idx
    on usage_events (person_key, day, surface);
create index if not exists usage_events_day_idx on usage_events (day desc);
create index if not exists usage_events_unit_idx on usage_events (unit_number, day desc);

alter table usage_events enable row level security;
grant select on usage_events to anon, authenticated;
grant select, insert on usage_events to service_role;

-- Nobody reads raw rows from a client -- the aggregate function below is the only view. (Admins can
-- still inspect the table with the service-role key when they need to.)
drop policy if exists usage_events_select on usage_events;
create policy usage_events_select on usage_events for select using (is_admin());

comment on table usage_events is
  'Usage telemetry (0066): one row per person per surface per DAY the app was opened. Deliberately '
  'name-free -- unit/stake/calling/role are derived server-side from the caller''s user_roles row and '
  'identity is kept only as a salted one-way person_key so distinct-people counts are possible. '
  'Read through usage_summary(); admin-only by RLS.';

-- The salt makes person_key unlinkable to an email by anyone holding only this table (without it,
-- a hash of a known address is trivially checkable). It lives in app_settings (owner-managed,
-- already service-role-only) and is minted once, lazily, on first use.
alter table app_settings add column if not exists usage_salt text;

create or replace function _usage_salt() returns text language plpgsql
security definer set search_path = public as $$
declare s text;
begin
    select usage_salt into s from app_settings where id limit 1;
    if s is null or s = '' then
        -- gen_random_uuid() is core (0001 already relies on it); pgcrypto's gen_random_bytes/digest
        -- live in the `extensions` schema on Supabase and would not resolve under this search_path.
        s := replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '');
        update app_settings set usage_salt = s where id;
        -- app_settings may not have its singleton row yet on a fresh database.
        if not found then
            insert into app_settings (id, usage_salt) values (true, s)
            on conflict (id) do update set usage_salt = excluded.usage_salt;
        end if;
    end if;
    return s;
end $$;
revoke all on function _usage_salt() from anon, authenticated;

-- record_app_open(surface): call once per app session. Idempotent for the day (the unique index
-- absorbs repeats), silent for a signed-out or unscoped caller, and never raises -- telemetry must
-- not be able to break an app open.
create or replace function record_app_open(p_surface text default 'web') returns void
language plpgsql security definer set search_path = public as $$
declare
    v_email text := _jwt_email();
    v_role  record;
begin
    if v_email is null then
        return;
    end if;
    if p_surface is null or p_surface not in ('web', 'ios', 'android') then
        p_surface := 'web';
    end if;

    -- The caller's OWN scope, most-specific first (a ward row names the unit they actually work in;
    -- a stake row is the fallback). Matched the way RLS matches: verified email OR bound auth_id.
    select r.stake_id, s.name as stake_name, u.unit_number, u.name as unit_name,
           r.calling_name, r.role
      into v_role
      from user_roles r
      left join stakes s on s.id = r.stake_id
      left join units  u on u.id = r.unit_id
     where lower(r.email) = v_email or r.auth_id = _jwt_uid()
     order by (r.unit_id is null), r.created_at
     limit 1;

    insert into usage_events (person_key, surface, stake_id, stake_name,
                              unit_number, unit_name, calling, role)
    values (md5(v_email || _usage_salt()), p_surface,
            v_role.stake_id, v_role.stake_name, v_role.unit_number, v_role.unit_name,
            nullif(btrim(coalesce(v_role.calling_name, '')), ''), v_role.role)
    on conflict (person_key, day, surface) do nothing;
exception when others then
    return;   -- never let telemetry fail an app open
end $$;
grant execute on function record_app_open(text) to authenticated;

-- usage_summary(days): the admin console's whole data source. Returns aggregate rows only --
-- ('unit'|'calling'|'surface', label, days_used, people, last_used) -- so there is nothing to leak
-- even by accident. Admin-gated: a non-admin gets an empty set, not an error.
create or replace function usage_summary(p_days integer default 30)
returns table (
    dimension text,
    label     text,
    events    bigint,   -- person-days: how often it was used
    people    bigint,   -- distinct people behind those days
    last_used date
)
language sql stable security definer set search_path = public as $$
    with scoped as (
        select * from usage_events
         where is_admin()
           and day >= ((now() at time zone 'utc')::date - greatest(coalesce(p_days, 30), 1))
    )
    select 'unit'::text, coalesce(unit_name, stake_name, 'Unknown unit'),
           count(*)::bigint, count(distinct person_key)::bigint, max(day)
      from scoped group by 2
    union all
    select 'calling'::text, coalesce(calling, 'No calling on file'),
           count(*)::bigint, count(distinct person_key)::bigint, max(day)
      from scoped group by 2
    union all
    select 'surface'::text, surface,
           count(*)::bigint, count(distinct person_key)::bigint, max(day)
      from scoped group by 2
    order by 1, 3 desc, 2;
$$;
grant execute on function usage_summary(integer) to authenticated;

-- usage_daily(days): the same scoped rows collapsed to a per-day total, for the trend sparkline.
create or replace function usage_daily(p_days integer default 30)
returns table (day date, events bigint, people bigint)
language sql stable security definer set search_path = public as $$
    select day, count(*)::bigint, count(distinct person_key)::bigint
      from usage_events
     where is_admin()
       and day >= ((now() at time zone 'utc')::date - greatest(coalesce(p_days, 30), 1))
     group by day order by day;
$$;
grant execute on function usage_daily(integer) to authenticated;

notify pgrst, 'reload schema';
