-- Covenant-path platform schema (Supabase / Postgres).
-- Multi-stake: every member row is tagged with stake_id + unit_id so Row-Level
-- Security can scope reads (stake leaders see their whole stake; ward leaders see
-- only their unit). The scraper writes via the postgres role (bypasses RLS);
-- viewers read via the Supabase API as `authenticated` (RLS enforced) — see 0002.

create extension if not exists pgcrypto;  -- gen_random_uuid()

create table if not exists stakes (
    id             uuid primary key default gen_random_uuid(),
    unit_number    bigint unique not null,
    name           text not null,
    onboarded_at   timestamptz default now(),
    last_synced_at timestamptz
);

create table if not exists units (
    id           uuid primary key default gen_random_uuid(),
    stake_id     uuid not null references stakes(id) on delete cascade,
    unit_number  bigint unique not null,
    name         text not null,
    unit_type    text,
    created_at   timestamptz default now()
);
create index if not exists units_stake_idx on units(stake_id);

create table if not exists members (
    id                            uuid primary key default gen_random_uuid(),
    stake_id                      uuid not null references stakes(id) on delete cascade,
    unit_id                       uuid references units(id) on delete set null,
    person_uuid                   text,            -- LCR personUuid (join key)
    name                          text,
    unit_name                     text,
    baptism_date                  text,
    birth_date                    text,
    friends                       text,
    aaronic_priesthood            text,
    melchizedek_priesthood        text,
    calling                       text,
    ministering_brothers_sisters  text,
    ministering_assignment        text,
    temple_recommend              text,
    patriarchal_blessing          text,
    living_ordinance              text,
    membership_duration           text,
    sex                           text,
    updated_at                    timestamptz default now(),
    unique (stake_id, person_uuid)
);
create index if not exists members_stake_idx on members(stake_id);
create index if not exists members_unit_idx  on members(unit_id);

-- App viewers (linked to Supabase auth.users). Roles drive RLS.
create table if not exists app_users (
    id         uuid primary key default gen_random_uuid(),
    auth_id    uuid unique,        -- = auth.users.id
    email      text unique,
    created_at timestamptz default now()
);

-- A role grants access to a stake; unit_id NULL = the WHOLE stake (stake leader),
-- unit_id set = only that ward/branch (ward leader).
create table if not exists user_roles (
    id         uuid primary key default gen_random_uuid(),
    auth_id    uuid not null,                          -- = auth.uid()
    stake_id   uuid not null references stakes(id) on delete cascade,
    unit_id    uuid references units(id) on delete cascade,
    role       text not null check (role in ('stake_leader','ward_leader','admin')),
    created_at timestamptz default now(),
    unique (auth_id, stake_id, unit_id, role)
);
create index if not exists user_roles_auth_idx on user_roles(auth_id);

-- keep members.updated_at honest on writes
create or replace function set_updated_at() returns trigger as $$
begin new.updated_at = now(); return new; end;
$$ language plpgsql;

drop trigger if exists members_updated_at on members;
create trigger members_updated_at before update on members
    for each row execute function set_updated_at();
