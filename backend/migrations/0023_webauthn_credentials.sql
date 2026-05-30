-- Passwordless passkey login (WebAuthn). Stores each registered passkey's public key bound to the
-- user's email (the identity RLS keys off). The broker runs the WebAuthn ceremonies with its
-- service-role key and mints a Supabase session on a verified assertion — so this table is managed
-- only by the broker (service_role); RLS on with no policy denies anon/authenticated. The public
-- key + credential id are NOT secrets (public-key crypto), but we lock the table anyway since it
-- maps credentials → identities. Additive + idempotent.

create table if not exists webauthn_credentials (
    id            uuid primary key default gen_random_uuid(),
    email         text not null,                 -- lowercased; the Supabase identity
    credential_id text not null unique,          -- base64url of the credential id
    public_key    text not null,                 -- base64url COSE public key
    sign_count    bigint not null default 0,
    transports    text[],
    created_at    timestamptz default now(),
    last_used_at  timestamptz
);
create index if not exists webauthn_email_idx on webauthn_credentials (lower(email));

alter table webauthn_credentials enable row level security;
grant select, insert, update, delete on webauthn_credentials to service_role;
