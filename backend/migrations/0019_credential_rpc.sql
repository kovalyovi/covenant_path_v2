-- Delegated onboarding (#51): the broker (service role) must write the RLS-locked
-- stake_credentials table without being granted broad access. A SECURITY DEFINER RPC,
-- owned by the migration role, does the upsert on its behalf (least privilege). Also add
-- coverage (what the stored session can pull) + access_rank (for most-elevated-wins).
-- Additive + idempotent.

alter table stake_credentials add column if not exists coverage    jsonb;
alter table stake_credentials add column if not exists access_rank integer;

create or replace function store_stake_credential(
    p_stake_id          uuid,
    p_principal_name    text,
    p_granting_role_ids integer[],
    p_credential_enc    text,
    p_coverage          jsonb,
    p_access_rank       integer,
    p_expires_at        timestamptz
) returns void
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into stake_credentials
        (stake_id, principal_name, granting_role_ids, credential_enc, coverage, access_rank,
         expires_at, revoked, updated_at)
    values (p_stake_id, p_principal_name, p_granting_role_ids, p_credential_enc, p_coverage,
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
        updated_at        = now();
end;
$$;

-- Only the broker's service role may call it; never anon/authenticated clients.
revoke all on function store_stake_credential(uuid, text, integer[], text, jsonb, integer, timestamptz) from public;
grant execute on function store_stake_credential(uuid, text, integer[], text, jsonb, integer, timestamptz) to service_role;
