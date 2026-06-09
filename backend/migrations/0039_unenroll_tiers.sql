-- Unenroll tiers (admin ops + provider self-service). Two SECURITY DEFINER functions so the
-- service-role broker can delete from the RLS-locked tables without broad DELETE grants (mirrors the
-- enroll_stake_credential pattern). Additive + idempotent.
--
--   wipe_stake_members  — delete a stake's MEMBER data only (keep the stake shell + roles + credential
--                         so it re-populates on the next sync / re-enroll). "Revoke + wipe data".
--   remove_stake        — FULL removal: credential + members + roles + comments + diagnostics + the
--                         stake row, as if it never onboarded. ADMIN ONLY. Irreversible.

create or replace function wipe_stake_members(p_stake_id uuid) returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
    delete from members where stake_id = p_stake_id;
    get diagnostics n = row_count;
    -- reset freshness so the app shows "setting up" rather than a stale member count.
    update stakes set sync_state = 'idle', last_synced_at = null where id = p_stake_id;
    return n;
end; $$;

create or replace function remove_stake(p_stake_id uuid) returns void
language plpgsql security definer set search_path = public as $$
begin
    -- explicit child deletes first (don't rely on a particular FK on-delete config), then the row.
    delete from stake_credentials where stake_id = p_stake_id;
    delete from members           where stake_id = p_stake_id;
    delete from user_roles        where stake_id = p_stake_id;
    delete from sync_diagnostics  where stake_id = p_stake_id;
    delete from stakes            where id        = p_stake_id;
end; $$;

revoke all on function wipe_stake_members(uuid) from public;
revoke all on function remove_stake(uuid) from public;
grant execute on function wipe_stake_members(uuid) to service_role;
grant execute on function remove_stake(uuid) to service_role;
