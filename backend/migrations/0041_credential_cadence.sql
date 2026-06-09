-- Authorization-cadence visibility (feedback: "how often do we need a fresh re-auth?").
-- has_refresh_token: whether the stored credential can SELF-RENEW (captured at enroll; the blob is
-- encrypted so the broker can't tell after the fact). Credentials without it (pre-2026-05-29 era)
-- die when their Okta session ages out (~days) and need manual re-auth; with it, re-auth should be
-- rare. Surfaced in the ops enrolled-stakes view next to credential age + re-auth counts.
-- Additive + idempotent.

alter table stake_credentials add column if not exists has_refresh_token boolean;

drop function if exists enroll_stake_credential(
    integer, text, text, text, integer[], text, jsonb, integer, timestamptz);

create or replace function enroll_stake_credential(
    p_unit_number       integer,
    p_stake_name        text,
    p_principal_name    text,
    p_principal_email   text,
    p_granting_role_ids integer[],
    p_credential_enc    text,
    p_coverage          jsonb,
    p_access_rank       integer,
    p_expires_at        timestamptz,
    p_has_refresh_token boolean default null
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
         access_rank, expires_at, has_refresh_token, revoked, updated_at)
    values (v_stake_id, p_principal_name, lower(p_principal_email), p_granting_role_ids,
            p_credential_enc, p_coverage, p_access_rank, p_expires_at, p_has_refresh_token, false, now())
    on conflict (stake_id) do update set
        principal_name    = excluded.principal_name,
        principal_email   = excluded.principal_email,
        granting_role_ids = excluded.granting_role_ids,
        credential_enc    = excluded.credential_enc,
        coverage          = excluded.coverage,
        access_rank       = excluded.access_rank,
        expires_at        = excluded.expires_at,
        has_refresh_token = excluded.has_refresh_token,
        revoked           = false,
        revoked_at        = null,
        updated_at        = now(),
        -- a successful (re)enroll captures a FRESH session -> clear the failing/notified state.
        last_failed_at    = null,
        last_error        = null,
        stale_notified_at = null
    where stake_credentials.revoked = true
       or coalesce((stake_credentials.coverage ->> 'complete')::boolean, false) = false
       or excluded.access_rank >= coalesce(stake_credentials.access_rank, -1)
       or lower(excluded.principal_email) = lower(coalesce(stake_credentials.principal_email, ''))
       or stake_credentials.last_failed_at is not null;

    return v_stake_id;
end;
$$;

revoke all on function enroll_stake_credential(integer, text, text, text, integer[], text, jsonb, integer, timestamptz, boolean) from public;
grant execute on function enroll_stake_credential(integer, text, text, text, integer[], text, jsonb, integer, timestamptz, boolean) to service_role;
