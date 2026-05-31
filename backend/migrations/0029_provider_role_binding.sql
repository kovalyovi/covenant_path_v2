-- Provider role binding (fixes "enroller sees 0 members" / father's Stake-Clerk login).
--
-- ROOT CAUSE: provision_roles() keys calling-derived rows by lcr_person_uuid and enriches
-- `email` from client.member_list() — an LCR endpoint that is currently dead (404). RLS matches
-- a viewer to a role by (auth_id = auth.uid()) OR (lower(email) = jwt email). For an email/Google
-- login (the common case) auth_id never equals the stored LCR uuid, and when member_list is down
-- the role's email is NULL — so the leader who SET THE STAKE UP sees zero of their own members.
--
-- FIX: the person who enrolls a stake is, by definition, a stake leader who must see it. Bind their
-- verified principal_email to a stake-wide stake_leader role at enroll time (the same email-scoped
-- mechanism power-user invites already use — see 0005). Endpoint-independent and self-healing.
--
-- This row has lcr_person_uuid = NULL, so the daily provision_roles() revoke step (which only deletes
-- calling-derived rows, lcr_person_uuid IS NOT NULL) never removes it. source='enrollment' keeps it
-- distinct from 'calling' and 'invitation' rows.

create or replace function enroll_stake_credential(
    p_unit_number   bigint,
    p_stake_name    text,
    p_principal_name text,
    p_granting_role_ids integer[],
    p_credential_enc text,
    p_coverage      jsonb,
    p_access_rank   integer,
    p_expires_at    timestamptz,
    p_principal_email text default null
)
returns uuid language plpgsql security definer set search_path = public as $$
declare
    v_stake_id uuid;
begin
    -- upsert the stake by unit_number; capture its id
    insert into stakes (unit_number, name)
    values (p_unit_number, p_stake_name)
    on conflict (unit_number) do update set name = excluded.name
    returning id into v_stake_id;

    insert into stake_credentials (stake_id, principal_name, granting_role_ids,
                                   credential_enc, coverage, access_rank, expires_at,
                                   principal_email, revoked, revoked_at, updated_at)
    values (v_stake_id, p_principal_name, p_granting_role_ids,
            p_credential_enc, p_coverage, p_access_rank, p_expires_at,
            lower(p_principal_email), false, null, now())
    on conflict (stake_id) do update set
        principal_name    = excluded.principal_name,
        granting_role_ids = excluded.granting_role_ids,
        credential_enc    = excluded.credential_enc,
        coverage          = excluded.coverage,
        access_rank       = excluded.access_rank,
        expires_at        = excluded.expires_at,
        principal_email   = excluded.principal_email,
        revoked           = false,
        revoked_at        = null,
        updated_at        = now();

    -- Bind the enroller as a stake-wide leader by their verified email, so they can read their
    -- stake immediately on first login regardless of LCR email enrichment (see header).
    if p_principal_email is not null and btrim(p_principal_email) <> '' then
        insert into user_roles (stake_id, unit_id, role, email, source)
        values (v_stake_id, null, 'stake_leader', lower(p_principal_email), 'enrollment')
        on conflict (stake_id, coalesce(unit_id, '00000000-0000-0000-0000-000000000000'::uuid),
                     role, coalesce(lcr_person_uuid, lower(email), ''))
        do nothing;
    end if;

    return v_stake_id;
end; $$;

grant execute on function enroll_stake_credential(bigint, text, text, integer[], text, jsonb, integer, timestamptz, text) to service_role;

-- Backfill: every already-enrolled, non-revoked provider gets the same stake_leader email binding
-- (idempotent — reconciles any rows already created out-of-band).
insert into user_roles (stake_id, unit_id, role, email, source)
select sc.stake_id, null, 'stake_leader', lower(sc.principal_email), 'enrollment'
from stake_credentials sc
where sc.principal_email is not null
  and btrim(sc.principal_email) <> ''
  and coalesce(sc.revoked, false) = false
on conflict (stake_id, coalesce(unit_id, '00000000-0000-0000-0000-000000000000'::uuid),
             role, coalesce(lcr_person_uuid, lower(email), ''))
do nothing;
