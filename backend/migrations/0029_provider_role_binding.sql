-- Provider role binding (fixes "enroller sees 0 members" / father's Stake-Clerk login).
--
-- ROOT CAUSE: provision_roles() keys calling-derived rows by lcr_person_uuid and stuffs the LCR
-- person uuid into auth_id, and enriches `email` from client.member_list() — an LCR endpoint that
-- is currently dead (404). RLS (0004) matches a viewer by (auth_id = auth.uid()) OR (lower(email)
-- = jwt email). An email/Google login never matches on auth_id (that holds the LCR uuid), and with
-- member_list down the role's email is NULL — so the leader who SET THE STAKE UP sees zero of their
-- own members.
--
-- FIX: the person who enrolls a stake is, by definition, a stake leader who must see it. Bind their
-- verified principal_email to a stake-wide stake_leader role whenever a (non-revoked) credential is
-- written — via a TRIGGER on stake_credentials, which is independent of the enroll RPC's exact
-- argument signature (there are historically several overloads). Endpoint-independent, self-healing.
--
-- The bound row has lcr_person_uuid = NULL and source='enrollment', so the daily provision_roles()
-- revoke step (which only deletes calling-derived rows, lcr_person_uuid IS NOT NULL) never drops it.

-- 0) Undo a mistaken overload an earlier draft of this migration created. CREATE OR REPLACE only
--    replaces an identical signature; the draft used (bigint,...,text default null), which ADDED a
--    second overload and made PostgREST's rpc/enroll_stake_credential ambiguous (broke enrollment).
--    Drop that specific overload; leave the canonical (integer,...) one (recreated by 0020/0024).
drop function if exists enroll_stake_credential(
    bigint, text, text, integer[], text, jsonb, integer, timestamptz, text);

-- 1) De-dupe any pre-existing duplicate role rows (same scope+subject), keeping the lowest id.
--    Guards the unique-key invariant before we (re)insert, and cleans rows a prior buggy run left.
delete from user_roles a
using user_roles b
where a.id > b.id
  and a.stake_id = b.stake_id
  and coalesce(a.unit_id, '00000000-0000-0000-0000-000000000000'::uuid)
      = coalesce(b.unit_id, '00000000-0000-0000-0000-000000000000'::uuid)
  and a.role = b.role
  and coalesce(a.lcr_person_uuid::text, lower(a.email), '')
      = coalesce(b.lcr_person_uuid::text, lower(b.email), '');

-- 2) Trigger: bind the credential provider's verified email to a stake-wide stake_leader role.
create or replace function bind_provider_stake_role() returns trigger
language plpgsql security definer set search_path = public as $$
begin
    if NEW.principal_email is not null and btrim(NEW.principal_email) <> ''
       and coalesce(NEW.revoked, false) = false then
        insert into user_roles (stake_id, unit_id, role, email, source)
        values (NEW.stake_id, null, 'stake_leader', lower(NEW.principal_email), 'enrollment')
        on conflict (stake_id, coalesce(unit_id, '00000000-0000-0000-0000-000000000000'::uuid),
                     role, coalesce(lcr_person_uuid, lower(email), ''))
        do nothing;
    end if;
    return NEW;
end; $$;

drop trigger if exists trg_bind_provider_stake_role on stake_credentials;
create trigger trg_bind_provider_stake_role
    after insert or update on stake_credentials
    for each row execute function bind_provider_stake_role();

-- 3) Backfill: every already-enrolled, non-revoked provider gets the stake_leader email binding now
--    (idempotent — the unique key + ON CONFLICT keep it to one row per provider/stake).
insert into user_roles (stake_id, unit_id, role, email, source)
select sc.stake_id, null, 'stake_leader', lower(sc.principal_email), 'enrollment'
from stake_credentials sc
where sc.principal_email is not null
  and btrim(sc.principal_email) <> ''
  and coalesce(sc.revoked, false) = false
on conflict (stake_id, coalesce(unit_id, '00000000-0000-0000-0000-000000000000'::uuid),
             role, coalesce(lcr_person_uuid, lower(email), ''))
do nothing;
