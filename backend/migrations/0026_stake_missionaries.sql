-- Full-time missionaries assigned to each ward/branch (from /mlt/orgs/missionary, #29).
-- Per-stake JSON keyed by unit name:
--   { "<unit_name>": [ {"name","phone","email","mission_name"}, ... ], ... }
-- Leadership-only data, read through the same RLS-scoped stakes row the app already reads.
alter table stakes add column if not exists missionaries jsonb;
