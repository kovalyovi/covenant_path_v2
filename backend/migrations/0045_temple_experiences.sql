-- Temple Ordinances and Experiences → tracked covenant-path fields: a prepared family name
-- (genealogy — LCR commitment "Prepare a Family Name for the Temple") and a first temple visit
-- (proxy baptisms — "Perform Baptisms for Deceased Ancestors"). Yes/No/N-A text like the other
-- status fields; sentinel-merged on upsert (see backend/db._merge_expr) so a degraded details
-- fetch never blanks a known value. Additive + idempotent.
alter table members add column if not exists family_name_prepared text;
alter table members add column if not exists first_temple_visit text;
