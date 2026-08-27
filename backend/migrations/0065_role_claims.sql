-- 0065: "I'm a leader, but I signed in with a different email" — a SECURE self-service claim.
--
-- THE GAP (2026-08-25): RLS matches a role row by verified email. A leader whose app sign-in address
-- differs from the one we hold (invited at a work address, signs in with a personal Google account,
-- etc.) resolves to NO scope and sees an empty app. 0063 fixed the case where we simply never
-- learned an address; this covers the case where we hold a DIFFERENT one. Their only route today is
-- to find a stake leader and ask for an invite.
--
-- THE FLOW. A signed-in, scope-less user gives their first + last name. We look them up in the
-- leadership roster (`units.staffing`, which carries person + person_uuid) and, if that person holds
-- a calling-derived role AND we have an email on record for them, we mail a single-use verification
-- link TO THAT ADDRESS. Clicking it grants their sign-in address the same scope.
--
-- WHY THAT IS SAFE:
--   * The secret goes only to the address already on record — a stranger who guesses a leader's name
--     learns nothing and receives nothing; only the real inbox owner can finish.
--   * Tokens are stored HASHED (sha256), single-use (`consumed_at`), and short-lived (`expires_at`),
--     so a leaked DB row can't be replayed and neither can a used link.
--   * The grant CLONES the matched person's existing rows — same stake, same unit, same role. It can
--     never escalate beyond what that leader already holds (the `invite_power_user` principle).
--   * The claim row is keyed by EMAIL with a NULL lcr_person_uuid, so `provision_roles` (which only
--     deletes calling-derived rows) never clobbers it, and 0063's identity triggers never overwrite
--     it either.
--   * Every attempt is audited here, matched or not — a name-guessing spree is visible.
--
-- PRIVACY: holds emails + names -> admin-only by RLS, like login_audit (0033).
-- Additive + idempotent.

create table if not exists role_claims (
    id             bigint generated always as identity primary key,
    at             timestamptz not null default now(),
    claimant_email text not null,               -- the address they are signed in with
    first_name     text,
    last_name      text,
    matched_person_uuid text,                   -- the leader we matched, when we matched one
    matched_name   text,
    sent_to_email  text,                        -- the on-record address the link was mailed to
    token_hash     text,                        -- sha256 of the single-use token (never the token)
    expires_at     timestamptz,
    consumed_at    timestamptz,
    granted_roles  integer,                     -- how many role rows the claim created
    status         text not null default 'sent' -- sent | consumed | no_match | no_email_on_record | expired
);

alter table role_claims enable row level security;
grant select on role_claims to anon, authenticated;
grant select, insert, update on role_claims to service_role;

drop policy if exists role_claims_select on role_claims;
create policy role_claims_select on role_claims for select using (is_admin());

create index if not exists role_claims_at_idx on role_claims (at desc);
-- the verify lookup is by token hash; partial so only live, unconsumed tokens are indexed
create index if not exists role_claims_token_idx on role_claims (token_hash)
    where token_hash is not null and consumed_at is null;

comment on table role_claims is
  'Audit + single-use tokens for the "I signed in with a different email" claim flow (0065). The '
  'token is stored HASHED; the grant clones the matched leader''s existing roles and can never '
  'escalate. Admin-only by RLS.';

notify pgrst, 'reload schema';
