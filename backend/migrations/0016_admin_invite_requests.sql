-- Owner-approved admin invites: an invite creates a pending request; the configured owner
-- (OWNER_EMAIL on the broker) gets an email with a random-token approve link, and only on
-- approval is the person added to app_admins. The broker (service role) owns this table;
-- clients never touch it. Additive + idempotent.

create table if not exists admin_invite_requests (
  id                 uuid primary key default gen_random_uuid(),
  email              text not null,
  requested_by_email text,
  token              text not null unique,
  status             text not null default 'pending',  -- pending | approved
  created_at         timestamptz not null default now(),
  decided_at         timestamptz
);

alter table admin_invite_requests enable row level security;  -- no client policies = no client access
grant select, insert, update on admin_invite_requests to service_role;
