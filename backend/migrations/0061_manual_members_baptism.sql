-- 0061: manual people gain a baptism date + optional assigned missionaries (+ Ricky-compat name split).
-- Additive + idempotent.
--
-- WHY: a leader adds a baptism candidate on the Baptisms page before LCR has a record — they want to
-- record a planned baptism DATE, and optionally which missionary companionship is teaching them. Ricky's
-- Mission-KPIs "manual people" carry first_name + last_initial + baptism_date + unit; we store those so
-- the two apps round-trip cleanly over the partner lane. `name` stays the canonical not-null display
-- field (existing UI + the name-match merge use it); first_name/last_initial are optional extras.
--
-- The daily sync's server-side merge (db.merge_manual_members) copies custom_notes onto the real member
-- when a matching record appears — unchanged by this migration; these columns just travel with the row.
--
-- Apply with: python -m backend.apply

alter table manual_members add column if not exists baptism_date  date;
alter table manual_members add column if not exists missionaries  jsonb;   -- optional companionship ref
alter table manual_members add column if not exists first_name    text;
alter table manual_members add column if not exists last_initial  text;

notify pgrst, 'reload schema';
