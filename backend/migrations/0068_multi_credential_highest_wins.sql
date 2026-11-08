-- MULTI-CREDENTIAL STAKES: take the HIGHEST credential when multiple callings enroll (D82).
--
-- WHAT CHANGED (2026-11-08, user directive): a stake may now hold MULTIPLE enrolled credentials
-- (one row per leader/calling), and the stake's EFFECTIVE credential is always the HIGHEST
-- access_rank among its live (non-revoked) rows. Enrolling NEVER refuses and NEVER downgrades
-- anything: a narrower credential is stored as a standby; a broader one becomes effective at once.
--
-- WHY (the 2026-11-08 report): ILYA re-authorized his own stake and was told "This stake's daily
-- sync is already provided by ILYA Kovalyov with broader access. Your access is narrower, so it was
-- left in place to avoid reducing coverage. No change is needed." His fresh session had scraped a
-- lower rank than his stored credential, so the single-row most-elevated-wins rule (0055) refused to
-- store it at all — even though he IS the provider, and even though the stored session was the one
-- that needed refreshing. A refused re-auth leaves the stake with a dead high-rank session and no
-- live fallback. Under this migration his re-auth is STORED under his own email; the sync keeps
-- running on the highest live credential, and if the top one later dies the next-highest standby
-- takes over with no re-enroll.
--
-- WHAT THIS SUPERSEDES (0055): the single-row model (stake_id PRIMARY KEY, ON CONFLICT (stake_id)
-- with a strict most-elevated-wins WHERE) DISCARDED narrower enrollments entirely. The "never
-- clobber a higher credential" guarantee is preserved — by selection, not by refusal: a lower
-- credential can never BECOME effective while a higher live one exists, but it is kept, so a stake
-- whose top credential dies is never left with nothing.
--
-- Per-leader rank is the HIGHEST that leader has demonstrated (greatest(old, new) on refresh), so
-- a flaky LCR scrape can never demote a leader below their own proven bar. A genuinely reduced
-- calling is still handled by revocation: the daily sync's _revoke_if_ineligible revokes a leader
-- whose calling no longer grants access, after which the next-highest standby becomes effective.
--
-- Additive + idempotent: CREATE UNIQUE INDEX IF NOT EXISTS + DO-block guards + CREATE OR REPLACE
-- of the existing 10-arg overload (same signature/grants). Apply with: python -m backend.apply

-- ---------------------------------------------------------------------------------------------------
-- 1. stake_credentials: one row per (stake, leader) instead of one row per stake.
--    stake_id stops being the primary key; a surrogate id becomes the PK so every row (and every
--    per-row token/state update) is addressable. Existing rows are untouched (one row per stake
--    today, so the new unique key can't collide).
do $$
begin
    if not exists (select 1 from information_schema.columns
                    where table_name = 'stake_credentials' and column_name = 'id') then
        alter table stake_credentials
            add column id bigint generated always as identity;
    end if;
end $$;

do $$
begin
    if exists (select 1 from pg_constraint where conname = 'stake_credentials_pkey') then
        alter table stake_credentials drop constraint stake_credentials_pkey;
    end if;
end $$;

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'stake_credentials_id_pkey') then
        alter table stake_credentials add constraint stake_credentials_id_pkey primary key (id);
    end if;
end $$;

-- One row per leader per stake. principal_email is lowercased by the enroll RPC on write (and by
-- save_credential), so a plain two-column unique key is enough; NULL emails (legacy rows that never
-- went through the RPC) stay distinct under it, which is safe — they can never collide with a
-- real enroll.
create unique index if not exists stake_credentials_stake_provider_key
    on stake_credentials (stake_id, principal_email);

-- Effective-credential selection: highest rank, freshest first, live rows only.
create index if not exists stake_credentials_effective_idx
    on stake_credentials (stake_id, access_rank desc nulls last, updated_at desc)
    where not revoked;

-- ---------------------------------------------------------------------------------------------------
-- 2. The enroll RPC: store EVERY enrollment; the effective credential is max rank among live rows.
--    Same signature/grants as 0055; the sub-unit guard is unchanged.
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
    v_stake_id      uuid;
    v_parent        text;
    v_in_email      text := lower(coalesce(p_principal_email, ''));
    v_had_rows      boolean;
    v_had_own_row   boolean;
    v_prior_email   text;
    v_prior_rank    integer;
    v_effective_email text;
    v_action        text;
    v_old_complete  boolean;
    v_new_complete  boolean;
    v_old_features  jsonb;
    v_new_features  jsonb;
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

    -- Snapshot the CURRENT effective holder (highest live rank) before the upsert, for the trail.
    select lower(principal_email), access_rank into v_prior_email, v_prior_rank
      from stake_credentials where stake_id = v_stake_id and not revoked
      order by access_rank desc nulls last, updated_at desc limit 1;
    select exists(select 1 from stake_credentials where stake_id = v_stake_id),
           exists(select 1 from stake_credentials
                   where stake_id = v_stake_id
                     and lower(coalesce(principal_email, '')) = v_in_email)
      into v_had_rows, v_had_own_row;

    -- Per-leader upsert: this leader's row is refreshed, never refused. Rank is the HIGHEST this
    -- leader has demonstrated (a degraded scrape can never demote them below their proven bar);
    -- coverage.complete is the OR of old/new, with the complete side's feature list winning (a
    -- complete side's features are the fuller set; when neither side is complete the fresh scrape
    -- is the live truth for this leader). The empty-email edge ('' when no email was captured) is
    -- stored as '' — not NULL — so ON CONFLICT (stake_id, principal_email) still matches it.
    select coalesce((coverage->>'complete')::boolean, false),
           coverage->'features'
      into v_old_complete, v_old_features
      from stake_credentials
     where stake_id = v_stake_id and lower(coalesce(principal_email, '')) = v_in_email;
    v_new_complete := coalesce((p_coverage->>'complete')::boolean, false);
    v_new_features := p_coverage->'features';

    insert into stake_credentials
        (stake_id, principal_name, principal_email, granting_role_ids, credential_enc, coverage,
         access_rank, expires_at, has_refresh_token, revoked, updated_at)
    values (v_stake_id, p_principal_name, v_in_email, p_granting_role_ids,
            p_credential_enc, p_coverage, p_access_rank, p_expires_at, p_has_refresh_token, false, now())
    on conflict (stake_id, principal_email) do update set
        principal_name    = excluded.principal_name,
        granting_role_ids = excluded.granting_role_ids,
        credential_enc    = excluded.credential_enc,
        coverage          = jsonb_build_object(
            'complete', v_old_complete or v_new_complete,
            'features', case when v_old_complete then v_old_features
                             else v_new_features end,
            'missing', case when v_old_complete
                            then (stake_credentials.coverage->'missing')
                            else (excluded.coverage->'missing') end),
        access_rank       = nullif(greatest(coalesce(stake_credentials.access_rank, -1),
                                            coalesce(excluded.access_rank, -1)), -1),
        expires_at        = excluded.expires_at,
        has_refresh_token = excluded.has_refresh_token,
        revoked           = false,
        revoked_at        = null,
        updated_at        = now(),
        -- a successful (re)enroll captures a FRESH session -> clear the failing/notified state.
        last_failed_at    = null,
        last_error        = null,
        stale_notified_at = null;

    -- Who is effective now? Highest live rank (freshest wins a tie).
    select lower(principal_email) into v_effective_email
      from stake_credentials where stake_id = v_stake_id and not revoked
      order by access_rank desc nulls last, updated_at desc limit 1;
    if not v_had_rows then
        v_action := 'enrolled';                         -- first credential for this stake
    elsif v_had_own_row then
        v_action := 'refreshed';                        -- same leader re-authorized
    elsif v_effective_email = v_in_email then
        v_action := 'took_over';                        -- this leader is now the effective provider
    else
        v_action := 'stored_backup';                    -- stored; a broader credential stays effective
    end if;

    insert into stake_credential_history
        (stake_id, action, principal_name, principal_email, access_rank, coverage_complete,
         has_refresh_token, prior_principal_email, prior_access_rank)
    values (v_stake_id, v_action, p_principal_name, v_in_email, p_access_rank,
            v_new_complete, p_has_refresh_token,
            v_prior_email, v_prior_rank);

    return v_stake_id;
end;
$$;

revoke all on function enroll_stake_credential(integer, text, text, text, integer[], text, jsonb, integer, timestamptz, boolean) from public;
grant execute on function enroll_stake_credential(integer, text, text, text, integer[], text, jsonb, integer, timestamptz, boolean) to service_role;

notify pgrst, 'reload schema';
