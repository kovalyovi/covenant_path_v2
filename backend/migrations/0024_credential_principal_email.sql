-- Fix "revoke / sync-now not visible to the credential's own provider" (#51 item 5). The enroll
-- path stored the LCR display NAME in principal_name, but the app's is_provider check compares the
-- signed-in EMAIL — so it never matched and the provider's own controls were hidden. Add a
-- principal_email column (the identity the app matches on) and thread it through the enroll RPC.
-- principal_name stays for display ("Provided by <name>"). Additive + idempotent.

alter table stake_credentials add column if not exists principal_email text;

-- Recreate the enroll RPC with the extra p_principal_email arg. Drop the old 8-arg signature first
-- so there's no overload ambiguity for PostgREST.
drop function if exists enroll_stake_credential(
    integer, text, text, integer[], text, jsonb, integer, timestamptz);

create or replace function enroll_stake_credential(
    p_unit_number       integer,
    p_stake_name        text,
    p_principal_name    text,
    p_principal_email   text,
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
        (stake_id, principal_name, principal_email, granting_role_ids, credential_enc, coverage,
         access_rank, expires_at, revoked, updated_at)
    values (v_stake_id, p_principal_name, lower(p_principal_email), p_granting_role_ids,
            p_credential_enc, p_coverage, p_access_rank, p_expires_at, false, now())
    on conflict (stake_id) do update set
        principal_name    = excluded.principal_name,
        principal_email   = excluded.principal_email,
        granting_role_ids = excluded.granting_role_ids,
        credential_enc    = excluded.credential_enc,
        coverage          = excluded.coverage,
        access_rank       = excluded.access_rank,
        expires_at        = excluded.expires_at,
        revoked           = false,
        revoked_at        = null,
        updated_at        = now()
    where stake_credentials.revoked = true
       or coalesce((stake_credentials.coverage ->> 'complete')::boolean, false) = false
       or excluded.access_rank > coalesce(stake_credentials.access_rank, -1);

    return v_stake_id;
end;
$$;

revoke all on function enroll_stake_credential(integer, text, text, text, integer[], text, jsonb, integer, timestamptz) from public;
grant execute on function enroll_stake_credential(integer, text, text, text, integer[], text, jsonb, integer, timestamptz) to service_role;
