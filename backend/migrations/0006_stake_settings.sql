-- Per-stake settings, incl. a stake's OWN Resend API key so its emails draw on its own
-- quota instead of the shared one (multi-tenant quota isolation). Secret + RLS-locked
-- with no policies/grants -> only the postgres role (backend) can read it.
create table if not exists stake_settings (
    stake_id           uuid primary key references stakes(id) on delete cascade,
    resend_api_key_enc text,                 -- Fernet-encrypted; null => use shared RESEND_API_KEY
    email_from         text,                 -- null => shared RESEND_FROM
    digest_enabled     boolean default true,
    updated_at         timestamptz default now()
);
alter table stake_settings enable row level security;   -- no policies => API roles can't read
