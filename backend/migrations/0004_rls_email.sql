-- Client auth via Supabase Auth (email magic-link / Google), not custom JWTs — the
-- project uses asymmetric (ECC) signing keys, so we can't mint our own tokens. RLS
-- therefore matches a role EITHER by a bound auth_id (auth.uid()) OR by the verified
-- email claim in the Supabase-issued JWT (auth.jwt()->>'email'). Email is provisioned
-- onto user_roles from LCR member data; the user signs in with that email and is scoped.

drop policy if exists members_select on members;
create policy members_select on members for select
using (
    exists (
        select 1 from user_roles ur
        where (ur.auth_id = auth.uid()
               or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
          and ur.stake_id = members.stake_id
          and (ur.unit_id is null or ur.unit_id = members.unit_id)
    )
);

drop policy if exists units_select on units;
create policy units_select on units for select
using (
    exists (
        select 1 from user_roles ur
        where (ur.auth_id = auth.uid()
               or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
          and ur.stake_id = units.stake_id
          and (ur.unit_id is null or ur.unit_id = units.id)
    )
);

drop policy if exists stakes_select on stakes;
create policy stakes_select on stakes for select
using (
    exists (
        select 1 from user_roles ur
        where (ur.auth_id = auth.uid()
               or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
          and ur.stake_id = stakes.id
    )
);

-- a viewer can read their own role rows (by auth id or email)
drop policy if exists user_roles_self on user_roles;
create policy user_roles_self on user_roles for select
using (auth_id = auth.uid()
       or lower(email) = lower(nullif(auth.jwt() ->> 'email', '')));
