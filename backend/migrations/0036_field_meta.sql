-- Per-field freshness (#data-correctness): when each member field was last successfully FETCHED vs
-- last ATTEMPTED, so the UI can flag stale fields and we NEVER blank a value the endpoint didn't
-- return this run. Map shape: {field: {"f": <last-fetched-iso>, "t": <last-tried-iso>}}.
-- Written by backend.db.upsert_members (the merge is computed in Python). Additive + idempotent.

alter table members add column if not exists field_meta jsonb not null default '{}'::jsonb;
