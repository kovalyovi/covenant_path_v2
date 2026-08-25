-- 0063: a provisioned leader must never sign in to an EMPTY app just because we never learned the
-- email they sign in with.
--
-- THE BUG (found 2026-08-25 from login_audit): RLS on members/units matches a role row by
--   ur.auth_id = auth.uid()   OR   lower(ur.email) = lower(jwt email)
-- `auth_id` holds the LCR PERSON UUID (what provision_roles keys on), never a Supabase auth.uid(),
-- so for an email-OTP / Google sign-in `user_roles.email` is the ONLY key that can match. It was
-- NULL on 202 of 218 Raleigh ward_leader rows (and 43/43 St Petersburg) because the sole enrichment
-- source -- the LCR member-list endpoint -- has been dead (404) for months.
--
-- `auth_broker/enroll._bind_identity_email` already stamps the verified email at Church-login time,
-- but only onto rows that ALREADY EXIST. Every auxiliary presidency (EQ/RS/Primary/YW/Sunday School
-- president) signed in BEFORE commit 019bc7d created their rows, so the bind was a no-op: six
-- confirmed leaders (Justin Fawson, Reed Hunsaker, Kevin Bonilla, Susie Youd, Julia Marcum, Sary
-- Sanhueza -- all has_calling=true) logged in successfully and saw nothing, with no way to know a
-- SECOND Church login was what they needed.
--
-- The binding is already durably recorded in `church_identities` (cmis_uuid = the LCR person uuid,
-- probe-verified in 0043). This migration reads it back out so the two facts converge no matter
-- which order they arrive in:
--   (1) one-time BACKFILL          -- heals everyone who already signed in
--   (2) church_identities trigger  -- a login binds instantly, even to rows created later
--   (3) user_roles BEFORE-INSERT   -- a role created later is born with the email already on it
-- backend/roles.py::_identity_emails does the same join at sync time (belt and braces).
-- Additive + idempotent.

-- (1) BACKFILL: stamp the verified login email onto every calling-derived row we can match.
update user_roles ur
   set email = ci.email
  from church_identities ci
 where ci.cmis_uuid = ur.lcr_person_uuid::text
   and nullif(ci.email, '') is not null
   and ur.lcr_person_uuid is not null
   and ur.email is distinct from lower(ci.email);

-- (2) A Church login (new or refreshed identity) binds onto that person's role rows immediately.
create or replace function bind_identity_email_to_roles() returns trigger
language plpgsql security definer set search_path to 'public' as $$
begin
  if nullif(new.email, '') is not null and nullif(new.cmis_uuid, '') is not null then
    begin
      update user_roles
         set email = lower(new.email)
       where lcr_person_uuid::text = new.cmis_uuid
         and email is distinct from lower(new.email);
    exception when others then
      -- observability must never break a login write
      null;
    end;
  end if;
  return new;
end $$;

drop trigger if exists church_identities_bind_roles on church_identities;
create trigger church_identities_bind_roles
  after insert or update of email, cmis_uuid on church_identities
  for each row execute function bind_identity_email_to_roles();

-- (3) A role row provisioned AFTER the person already signed in is born with their email.
create or replace function fill_role_email_from_identity() returns trigger
language plpgsql security definer set search_path to 'public' as $$
begin
  if new.email is null and new.lcr_person_uuid is not null then
    begin
      select lower(ci.email) into new.email from church_identities ci
       where ci.cmis_uuid = new.lcr_person_uuid::text
         and nullif(ci.email, '') is not null
       limit 1;
    exception when others then
      null;
    end;
  end if;
  return new;
end $$;

drop trigger if exists user_roles_fill_email on user_roles;
create trigger user_roles_fill_email
  before insert on user_roles
  for each row execute function fill_role_email_from_identity();

notify pgrst, 'reload schema';
