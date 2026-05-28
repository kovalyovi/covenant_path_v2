-- Stake-level KPIs for the viewer's KPIs tab, sourced from LCR's dashboard widget endpoint
-- (/api/dashboard/data): new-member + people-being-taught counts, monthly sacrament
-- attendance, temple recommends, ministering interviews. Stored per stake; the app reads it
-- under the existing stakes_select RLS policy (a leader sees only their own stake's row).
-- Additive + idempotent.

alter table stakes add column if not exists kpis            jsonb;
alter table stakes add column if not exists kpis_updated_at timestamptz;
