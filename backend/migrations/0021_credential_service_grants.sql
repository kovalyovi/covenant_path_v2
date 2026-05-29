-- The broker now READS stake_credentials + user_roles directly with the service-role key over
-- PostgREST (admin enrolled-stakes ops view, per-user enrollment-status, provider/admin revoke).
-- Earlier the broker only WROTE stake_credentials via the SECURITY DEFINER enroll RPC (which runs
-- as owner and needs no grant), so the table was left ungranted — hence "permission denied (42501)"
-- on the new reads. Grant exactly what the broker needs; service_role bypasses RLS but still needs
-- table-level privileges. Safe: service_role lives only server-side, and credential_enc is
-- envelope-encrypted with CP_TOKEN_KEY (never in the DB) — a row read yields unreadable ciphertext.
-- Additive + idempotent.

grant select on user_roles to service_role;
grant select, update on stake_credentials to service_role;
