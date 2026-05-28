-- Coarse live sync status so the app can show "syncing your stake…" during a run (and the
-- "setting up your stake" state on a brand-new stake's first sync). Set to 'running' at the
-- start of a stake's sync and 'done' at the end. Additive + idempotent; readable under the
-- existing stakes RLS (a user already sees their own stake row).

alter table stakes add column if not exists sync_state      text;
alter table stakes add column if not exists sync_started_at timestamptz;
