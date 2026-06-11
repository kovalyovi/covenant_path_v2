-- Multi-stake cloud: per-stake credentials live in Supabase (not a local file), and
-- user_roles can be PROVISIONED from LCR callings before the person ever logs in
-- (auth_id is bound on first sign-in). This realizes the master plan's "permissions
-- rebuilt from callings, no manual role assignment."

-- Per-stake encrypted credential (the delegated session/token). Secret: RLS-on with
-- NO policies + no grants => the API roles (anon/authenticated) can't read it; only the
-- postgres role (scraper, via SUPABASE_DB_URL) reaches it.
create table if not exists stake_credentials (
    stake_id          uuid primary key references stakes(id) on delete cascade,
    principal_name    text,
    granting_role_ids integer[],
    credential_enc    text not null,                 -- Fernet-encrypted JSON blob
    granted_at        timestamptz default now(),
    expires_at        timestamptz,
    revoked           boolean default false,
    revoked_at        timestamptz,
    audit             jsonb default '[]'::jsonb,
    updated_at        timestamptz default now()
);
alter table stake_credentials enable row level security;   -- no policies => deny to API roles

-- user_roles: allow provisioning by LCR identity before a Supabase login exists.
alter table user_roles add column if not exists email           text;
alter table user_roles add column if not exists calling_name    text;
alter table user_roles add column if not exists lcr_person_uuid text;
alter table user_roles alter column auth_id drop not null;     -- bound on first login

-- replace the auth_id-based unique with a provisioning key (one row per
-- person+role+scope within a stake), so upserts on each sync are idempotent.
alter table user_roles drop constraint if exists user_roles_auth_id_stake_id_unit_id_role_key;
-- REPLAY GUARD (2026-06-11): 0005 DROPS this index and supersedes it with
-- user_roles_subject_key (adds email to the key for invitation rows). backend.apply replays
-- every file, so a bare CREATE here would fail on any populated db holding two same-scope
-- invited users (unique by email, duplicate under THIS older key) — first hit on the seeded
-- test project; prod would hit it with its second stake-wide power user. Recreate the legacy
-- key only while the successor doesn't exist yet (i.e. a genuinely fresh bootstrap mid-replay).
do $$
begin
    if not exists (select 1 from pg_indexes where indexname = 'user_roles_subject_key')
       and not exists (select 1 from pg_indexes where indexname = 'user_roles_provision_key') then
        execute $idx$create unique index user_roles_provision_key on user_roles (
            stake_id,
            coalesce(unit_id, '00000000-0000-0000-0000-000000000000'::uuid),
            role,
            coalesce(lcr_person_uuid, '')
        )$idx$;
    end if;
end $$;
