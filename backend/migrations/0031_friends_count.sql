-- #3 Surface friends count: persist the number of friends LCR recorded (len of the friends
-- array), so the app can show "N friends" instead of just Yes/No. Nullable — a degraded run
-- that couldn't determine it stores NULL and the upsert preserves the last-good count
-- (see backend/db._merge_expr). Additive + idempotent.
alter table members add column if not exists friends_count int;
