-- Block a WARD/BRANCH from ever being enrolled as a STAKE — the Green Level Ward incident (2026-06-13).
--
-- ROOT CAUSE: enroll_stake_credential keys the credential by the enrolling leader's unit number. A
-- WARD-level leader (e.g. a Ward Mission Leader) signing in with sync consent passed THEIR ward's unit
-- number, so the RPC happily created a brand-new "stake" row for that ward. Worse, that ward leader's
-- Member Tools token returns the PARENT STAKE as its org root while exposing covenant-path data for
-- only their ward — so the daily sync then wrote the ward's handful of members onto the WHOLE parent
-- stake and reconciled every other ward's members away (Raleigh: 93 members -> 7, all "Green Level
-- Ward"). The leader saw a ward view; the stake leader lost their stake view.
--
-- DEFENSE IN DEPTH (this migration is the DB backstop):
--   • backend/auth_broker/enroll.py refuses to enroll a ward/branch-level session (can_enroll=False),
--   • backend/sync.py raises CredentialScopeMismatch if a credential resolves to a sub-unit of its
--     Member Tools org root and the delegated sync revokes it,
--   • and HERE: enroll_stake_credential RAISES if p_unit_number is a unit we already know to be a
--     WARD/BRANCH beneath some stake (it appears in `units` with that type). A stake's own unit number
--     never appears in `units` as a ward, so a genuine stake enroll/re-enroll is unaffected, and the
--     very first enroll of a brand-new (never-synced) stake still works (its wards aren't in `units`
--     yet — the broker-layer ward gate covers that case).
-- Additive + idempotent: CREATE OR REPLACE of the existing 10-arg overload, same signature/grants.

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
    v_parent   text;
begin
    -- Reject a sub-unit masquerading as a stake. If this unit is already known as a WARD/BRANCH of a
    -- stake, enrolling it would create a duplicate "stake" and let one ward overwrite the real stake.
    select s.name into v_parent
      from units u join stakes s on s.id = u.stake_id
     where u.unit_number = p_unit_number
       and upper(coalesce(u.unit_type, '')) in ('WARD', 'BRANCH')
     limit 1;
    if v_parent is not null then
        raise exception 'unit % is a ward/branch of stake "%" and cannot be enrolled as a stake; a '
                        'ward leader sees their unit via their ward_leader role',
                        p_unit_number, v_parent
            using errcode = 'check_violation';
    end if;

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
