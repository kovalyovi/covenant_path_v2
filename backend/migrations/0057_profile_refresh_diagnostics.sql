-- On-demand profile refresh (the fill-data sheet, 2026-07-06): the broker's profile-refresh
-- worker records each run's outcome to sync_diagnostics (kind='profile_refresh') so the
-- fill-data sheet and the ops console can report "last filled N fields at T". The table's
-- writers were the postgres-role sync only; the broker's service role had SELECT only
-- (migration 0013), so the INSERT needs its own grant. Additive + idempotent.

grant insert on sync_diagnostics to service_role;

notify pgrst, 'reload schema';
