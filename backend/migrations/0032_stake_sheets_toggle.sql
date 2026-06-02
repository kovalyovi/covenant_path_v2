-- #5b: per-stake "generate Google Sheets" toggle. Default OFF — a stake leader opts in from
-- Settings (with a consent note); otherwise no spreadsheets are created or maintained (the data is
-- already in the app, so there's nothing to waste effort on). Also stores the per-ward spreadsheet
-- ids (the master/stake sheet id stays in `spreadsheet_id`). Additive + idempotent.

alter table stakes add column if not exists sheets_enabled    boolean not null default false;
alter table stakes add column if not exists ward_spreadsheets  jsonb   not null default '{}'::jsonb;

-- A stake leader toggles their own stake's sheet generation. SECURITY DEFINER so the RLS-locked
-- `stakes` table can be updated by a verified stake leader — matched by verified JWT email OR bound
-- auth_id, mirroring the rest of the access model (ADR provider-binding). Returns the new value.
create or replace function set_stake_sheets_enabled(p_stake_id uuid, p_enabled boolean)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
    if not exists (
        select 1 from user_roles
        where stake_id = p_stake_id
          and role = 'stake_leader'
          and (lower(email) = lower(auth.jwt() ->> 'email') or auth_id = auth.uid())
    ) then
        raise exception 'not authorized: only a stake leader can toggle sheet generation';
    end if;
    update stakes set sheets_enabled = p_enabled where id = p_stake_id;
    return p_enabled;
end;
$$;

revoke all on function set_stake_sheets_enabled(uuid, boolean) from public;
grant execute on function set_stake_sheets_enabled(uuid, boolean) to authenticated;
