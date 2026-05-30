-- Per-stake Google Sheet (#1/#2): each stake gets its OWN spreadsheet instead of sheets appended
-- to one shared master. Store the per-stake spreadsheet id here; the sync creates + shares it
-- (read-only, to the stake's leadership + the onboarder) on first sync and reuses it after.
-- spreadsheet_shared is a cache of emails already granted, so we don't re-share every run.
-- Additive + idempotent.

alter table stakes add column if not exists spreadsheet_id     text;
alter table stakes add column if not exists spreadsheet_shared text[];
