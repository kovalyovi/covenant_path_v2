-- Row-Level Security: the heart of the access model.
--
--   stake_leader  (user_roles.unit_id IS NULL) -> sees EVERY member in the stake
--   ward_leader   (user_roles.unit_id = X)      -> sees only members in unit X
--
-- RLS applies to the `anon`/`authenticated` roles used by the Supabase API + a
-- user's JWT (auth.uid()). The scraper connects as the `postgres` role over the DB
-- URL, which bypasses RLS (table owner) — so writes are unrestricted while reads
-- through the app are scoped. (We deliberately do NOT FORCE RLS on the owner.)

-- API roles need table grants (RLS then scopes the rows); without a JWT (anon),
-- auth.uid() is null so the policies below return zero rows.
grant usage on schema public to anon, authenticated;
grant select on stakes, units, members, user_roles to anon, authenticated;

alter table stakes      enable row level security;
alter table units       enable row level security;
alter table members     enable row level security;
alter table user_roles  enable row level security;

-- a member is visible if the viewer holds a matching role:
--   whole-stake role (unit_id null) matching the member's stake, OR
--   ward role whose unit_id matches the member's unit.
drop policy if exists members_select on members;
create policy members_select on members for select
using (
    exists (
        select 1 from user_roles ur
        where ur.auth_id = auth.uid()
          and ur.stake_id = members.stake_id
          and (ur.unit_id is null or ur.unit_id = members.unit_id)
    )
);

-- stakes: visible if the viewer has any role in that stake
drop policy if exists stakes_select on stakes;
create policy stakes_select on stakes for select
using (
    exists (select 1 from user_roles ur
            where ur.auth_id = auth.uid() and ur.stake_id = stakes.id)
);

-- units: whole-stake roles see all units; ward roles see only their unit
drop policy if exists units_select on units;
create policy units_select on units for select
using (
    exists (
        select 1 from user_roles ur
        where ur.auth_id = auth.uid()
          and ur.stake_id = units.stake_id
          and (ur.unit_id is null or ur.unit_id = units.id)
    )
);

-- a viewer can read their own role rows
drop policy if exists user_roles_self on user_roles;
create policy user_roles_self on user_roles for select
using (auth_id = auth.uid());
