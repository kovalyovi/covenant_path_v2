-- In-app sync schedule: let a stake's provider choose WHEN the daily sync runs (ET hour) and
-- pause/resume it — instead of the hardcoded 7am. Columns live on the existing RLS-locked
-- stake_settings table (no API-role grants; only the postgres role + service_role read it). All
-- additive with defaults, so existing stakes keep today's behavior (7:00 ET, not paused) with no row.
alter table stake_settings add column if not exists sync_hour_et integer not null default 7;   -- 0–23 ET
alter table stake_settings add column if not exists sync_paused boolean not null default false;

-- guardrail: keep the hour in range (a bad client value can't wedge the matrix gate)
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'stake_settings_sync_hour_chk') then
    alter table stake_settings add constraint stake_settings_sync_hour_chk
      check (sync_hour_et between 0 and 23);
  end if;
end $$;
