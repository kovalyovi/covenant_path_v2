-- B8 credential-longevity alert (docs/TESTING.md): a credential WITHOUT a refresh token cannot
-- self-renew — it dies with its Okta session, and until now the provider only heard about it
-- AFTER the sync started failing (the stale alert). age_notified_at dedupes a PRE-EMPTIVE nudge
-- sent while the sync is still healthy: one alert per credential GENERATION, because every
-- (re-)enroll bumps updated_at and `age_notified_at < updated_at` re-arms automatically — no RPC
-- change needed. Additive + idempotent.

alter table stake_credentials add column if not exists age_notified_at timestamptz;
