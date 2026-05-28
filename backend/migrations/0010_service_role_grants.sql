-- The auth broker reads these tables with the SERVICE-ROLE key over PostgREST to power the
-- admin console: verify_admin() looks up app_admins, and the summary panel counts members /
-- units / stakes + reads freshness. service_role bypasses RLS but still needs table-level
-- SELECT, and earlier migrations only granted anon/authenticated — so the broker got
-- "permission denied (42501)" and every admin check failed with "not an admin".
-- Grant exactly the broker's reads. Additive + idempotent.

grant select on app_admins, members, units, stakes to service_role;
