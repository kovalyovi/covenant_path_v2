-- service_role bypasses RLS but still needs TABLE-LEVEL privileges, and we've been granting them
-- piecemeal (0010 select-only on 4 tables, 0021 credentials, 0028 gdrive...). Every miss is a
-- SILENT 42501 — the identity-cache outage and the test-project seeding both died on it. One
-- catch-all: service_role gets full DML on everything in public, current and future (default
-- privileges cover tables created by later migrations), so a brand-new project bootstrapped from
-- migrations behaves exactly like production. anon/authenticated stay RLS-scoped as before.
-- Additive + idempotent.

grant usage on schema public to service_role;
grant all privileges on all tables in schema public to service_role;
grant all privileges on all sequences in schema public to service_role;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;

-- PostgREST caches schema/privileges — reload so the grants take effect immediately.
notify pgrst, 'reload schema';
