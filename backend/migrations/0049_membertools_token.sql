-- 0049: Persist the Member Tools 45-day refresh token per stake, in Supabase. Additive + idempotent.
--
-- WHY (2026-06-12 sync outage): the daily covenant-path sync pulls the whole stake from the Member
-- Tools bulk API (/api/v5/sync), whose bearer is minted by a SILENT (prompt=none) OAuth authorize
-- that needs a LIVE Okta WEB session. A delegated stake's stored credential keeps a long-lived LCR
-- appSession but its Okta web session dies within hours/days — so `mint_from_okta_session` fails with
-- `login_required` and the stake stops syncing until re-authorized (exactly the stake-503991 report:
-- "as soon as I enroll it asks me to re-authorize"). The Member Tools token, however, comes WITH a
-- 45-day REFRESH token that renews an access token with NO Okta session at all — but it was only ever
-- cached in the local file store (`tools/output/delegated_grants.enc`), which does NOT persist across
-- the ephemeral CI runners that run the daily sync. So it never accumulated and every run re-minted
-- (and failed once the Okta session died).
--
-- FIX: store the Member Tools refresh token alongside the delegated credential (Fernet-encrypted,
-- same envelope key as credential_enc), bootstrapped at ENROLL while the session is fresh+mintable.
-- The daily sync then renews off it for 45 days regardless of Okta-session longevity or MFA.
--
-- Apply with: python -m backend.apply

alter table stake_credentials
  add column if not exists membertools_refresh_enc text;        -- Fernet(JSON {"refresh_token": ...})
alter table stake_credentials
  add column if not exists membertools_minted_at  timestamptz;  -- 45-day clock anchor (preserved across refreshes)

comment on column stake_credentials.membertools_refresh_enc is
  'Encrypted Member Tools 45-day refresh token (migration 0049): renews the /api/v5/sync bearer with no Okta web session. Bootstrapped at enroll. Service-role only (table RLS denies API roles).';

-- service_role already has full table grants (migration 0046); RLS has no policies so API roles
-- can't read these columns. No new grants needed.
