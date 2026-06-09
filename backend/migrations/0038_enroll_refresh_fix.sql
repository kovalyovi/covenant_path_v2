-- Fix "re-enrollment never refreshes a stale credential" + add groundwork for stale-credential alerts.
--
-- BUG (root-caused 2026-06-09): enroll_stake_credential only REPLACED the stored credential on a
-- strict access-rank UPGRADE (excluded.access_rank > existing). So when the SAME provider (or an
-- equally-capable leader) re-signed in to REFRESH an expired session, the ON CONFLICT update was
-- skipped — the dead session was kept and the daily delegated sync failed forever ("SSO did not
-- complete — landed back on Okta"). Real case: SPb (615145) stranded on its 2026-05-31 session for
-- 8 days even though the provider re-enrolled (audit showed "enrolled", but the blob never changed).
--
-- FIX: also refresh when (a) the new session is from the SAME principal (you can always renew your
-- own session), (b) access is EQUAL-or-higher (a fresher session from an equally-capable leader wins
-- — freshness matters for a browser session), or (c) the stored credential is currently FAILING
-- (last_failed_at set) so any authorized leader can TAKE OVER a dead one. A strictly-LOWER-access
-- different leader still can't clobber a HEALTHY higher-access credential. A successful (re)enroll
-- clears the failing state. Additive + idempotent.

-- Staleness columns (set by the sync on success/failure; consumed by alerts, the ops view, and the
-- takeover clause below). last_succeeded_at lets the mailer fire only on the success->failure edge.
alter table stake_credentials add column if not exists last_failed_at    timestamptz;
alter table stake_credentials add column if not exists last_error        text;
alter table stake_credentials add column if not exists last_succeeded_at timestamptz;
alter table stake_credentials add column if not exists stale_notified_at timestamptz;

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

revoke all on function enroll_stake_credential(integer, text, text, text, integer[], text, jsonb, integer, timestamptz) from public;
grant execute on function enroll_stake_credential(integer, text, text, text, integer[], text, jsonb, integer, timestamptz) to service_role;
