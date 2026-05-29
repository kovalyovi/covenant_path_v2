-- Onboarding enroll (#51): one privileged call that (a) ensures the stakes row exists for the
-- enrolling leader's unit and (b) stores their encrypted session as that stake's credential,
-- applying "most-elevated-wins-if-incomplete" atomically. SECURITY DEFINER so the service-role
-- broker can do it without broad grants on the RLS-locked tables. Returns the stake id.
-- Additive + idempotent.

create or replace function enroll_stake_credential(
    p_unit_number       integer,
    p_stake_name        text,
    p_principal_name    text,
    p_granting_role_ids integer[],
    p_credential_enc    text,
    p_coverage          jsonb,
    p_access_rank       integer,
    p_expires_at        timestamptz
) returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
    v_stake_id uuid;
begin
    insert into stakes (unit_number, name)
    values (p_unit_number, p_stake_name)
    on conflict (unit_number) do update set name = excluded.name
    returning id into v_stake_id;

    insert into stake_credentials
        (stake_id, principal_name, granting_role_ids, credential_enc, coverage, access_rank,
         expires_at, revoked, updated_at)
    values (v_stake_id, p_principal_name, p_granting_role_ids, p_credential_enc, p_coverage,
            p_access_rank, p_expires_at, false, now())
    on conflict (stake_id) do update set
        principal_name    = excluded.principal_name,
        granting_role_ids = excluded.granting_role_ids,
        credential_enc    = excluded.credential_enc,
        coverage          = excluded.coverage,
        access_rank       = excluded.access_rank,
        expires_at        = excluded.expires_at,
        revoked           = false,
        revoked_at        = null,
        updated_at        = now()
    -- most-elevated-wins-if-incomplete: only replace an existing credential when it's revoked,
    -- its coverage is incomplete, or the new session has strictly higher access.
    where stake_credentials.revoked = true
       or coalesce((stake_credentials.coverage ->> 'complete')::boolean, false) = false
       or excluded.access_rank > coalesce(stake_credentials.access_rank, -1);

    return v_stake_id;
end;
$$;

revoke all on function enroll_stake_credential(integer, text, text, integer[], text, jsonb, integer, timestamptz) from public;
grant execute on function enroll_stake_credential(integer, text, text, integer[], text, jsonb, integer, timestamptz) to service_role;
