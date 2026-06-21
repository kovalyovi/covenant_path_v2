-- MOST-ELEVATED-WINS, for real — the Raleigh / Ricky incident (2026-06-18).
--
-- WHAT HAPPENED: stake_credentials holds exactly ONE row per stake (keyed by stake_id). The enroll
-- RPC's ON CONFLICT decided who "wins" that single slot. Its WHERE clause had TWO rank-UNGATED escape
-- hatches:
--     or coalesce((coverage->>'complete')::boolean,false) = false   -- existing incomplete -> ANYONE replaces
--     or stake_credentials.last_failed_at is not null               -- existing failing   -> ANYONE replaces
-- A stake clerk (ILYA) held a rank-1000, complete credential. It had no refresh token, so its Okta
-- session aged out and a sync stamped last_failed_at. A Stake High Councilor (Ricky, rank 4, INCOMPLETE)
-- then enrolled — and the `last_failed_at is not null` hatch let his rank-4 session overwrite the
-- rank-1000 one. A LOWER-access leader clobbered a HIGHER one, and the higher leader (who never revoked
-- anything) had no way to reclaim. Both symptoms trace to those ungated hatches.
--
-- THE RULE NOW (strict most-elevated-wins): the stake's sync credential is replaced ONLY when the
-- incoming session is at least as privileged as the stored one, OR is the same leader refreshing, OR
-- the stored one is fully revoked (genuinely dead/invalid). A strictly LOWER-access leader can NEVER
-- overwrite a higher one — not even when the stored credential is incomplete or temporarily failing.
-- A failing/incomplete HIGHER credential heals when ITS leader (or an equal/higher one) re-authorizes;
-- if that leader is truly gone, their calling lapses and the daily sync's _revoke_if_ineligible revokes
-- the credential, after which anyone may take over. (This intentionally reverses the old
-- "lower CAN take over a failing/incomplete credential" policy — see scenario_enroll_most_elevated_wins.)
--
-- Also adds stake_credential_history: stake_credentials keeps only the CURRENT holder, so every prior
-- enroll/takeover/refusal was lost. We now persist an append-only trail (who provided, their rank, whom
-- they replaced, and REFUSED downgrade attempts) so "who gave the credential / who tried to take it over"
-- is answerable. The RPC writes one history row per enroll attempt that reaches it.
--
-- Additive + idempotent: CREATE TABLE IF NOT EXISTS + CREATE OR REPLACE of the existing 10-arg overload
-- (same signature/grants). Apply with: python -m backend.apply

-- ---------------------------------------------------------------------------------------------------
-- 1. Append-only credential history. Read by the broker (service role); RLS-on with no client policy so
--    only the service role (which bypasses RLS) can see it — the raw trail can name leaders by email.
create table if not exists stake_credential_history (
    id                       bigint generated always as identity primary key,
    stake_id                 uuid not null references stakes(id) on delete cascade,
    action                   text not null,   -- enrolled | took_over | refreshed | blocked_downgrade
    principal_name           text,
    principal_email          text,
    access_rank              integer,
    coverage_complete        boolean,
    has_refresh_token        boolean,
    prior_principal_email    text,
    prior_access_rank        integer,
    created_at               timestamptz not null default now()
);
create index if not exists stake_credential_history_stake_idx
    on stake_credential_history (stake_id, created_at desc);

alter table stake_credential_history enable row level security;
-- No client SELECT/INSERT policy on purpose: only the service role reads/writes it (it bypasses RLS).
revoke all on stake_credential_history from anon, authenticated;
grant all on stake_credential_history to service_role;

-- ---------------------------------------------------------------------------------------------------
-- 2. The enroll RPC: strict most-elevated-wins + history logging. Keeps the sub-unit (ward/branch)
--    guard from 0052 unchanged.
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
    v_stake_id     uuid;
    v_parent       text;
    v_prior_email  text;
    v_prior_rank   integer;
    v_cur_email    text;
    v_action       text;
    v_in_email     text := lower(p_principal_email);
begin
    -- Reject a sub-unit masquerading as a stake (the Green Level Ward incident, 2026-06-13). If this
    -- unit is already known as a WARD/BRANCH of a stake, enrolling it would create a duplicate "stake"
    -- and let one ward overwrite the real stake.
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

    -- Snapshot the CURRENT holder before the upsert so we can record what (if anything) changed.
    select lower(principal_email), access_rank into v_prior_email, v_prior_rank
      from stake_credentials where stake_id = v_stake_id;

    insert into stake_credentials
        (stake_id, principal_name, principal_email, granting_role_ids, credential_enc, coverage,
         access_rank, expires_at, has_refresh_token, revoked, updated_at)
    values (v_stake_id, p_principal_name, v_in_email, p_granting_role_ids,
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
    where
        -- (1) the SAME leader re-authorizing -> always refresh their own credential (fresh session).
        lower(stake_credentials.principal_email) = v_in_email
        -- (2) the stored credential is fully revoked (dead/invalid) -> any authorized leader may take over.
        or stake_credentials.revoked = true
        -- (3) MOST-ELEVATED-WINS: the incoming session is at least as privileged as the stored one. A
        --     strictly LOWER-access leader can NEVER overwrite a higher one, even when the stored
        --     credential is incomplete or temporarily failing (the Ricky/Raleigh incident). `null >= x`
        --     is NULL (falsy), so a rank-less incoming can't win this arm against a ranked holder.
        or excluded.access_rank >= coalesce(stake_credentials.access_rank, -1);

    -- Did it stick? Re-read the current holder and classify for the history trail.
    select lower(principal_email) into v_cur_email from stake_credentials where stake_id = v_stake_id;
    if v_prior_email is null then
        v_action := 'enrolled';                         -- first credential for this stake
    elsif v_cur_email = v_in_email and v_prior_email = v_in_email then
        v_action := 'refreshed';                        -- same leader re-authorized
    elsif v_cur_email = v_in_email then
        v_action := 'took_over';                        -- replaced a different (<=) provider
    else
        v_action := 'blocked_downgrade';                -- a lower-access leader was refused
    end if;

    insert into stake_credential_history
        (stake_id, action, principal_name, principal_email, access_rank, coverage_complete,
         has_refresh_token, prior_principal_email, prior_access_rank)
    values (v_stake_id, v_action, p_principal_name, v_in_email, p_access_rank,
            coalesce((p_coverage->>'complete')::boolean, false), p_has_refresh_token,
            v_prior_email, v_prior_rank);

    return v_stake_id;
end;
$$;

revoke all on function enroll_stake_credential(integer, text, text, text, integer[], text, jsonb, integer, timestamptz, boolean) from public;
grant execute on function enroll_stake_credential(integer, text, text, text, integer[], text, jsonb, integer, timestamptz, boolean) to service_role;

notify pgrst, 'reload schema';
