-- Weekly reminder history: a per-stake snapshot of each baptized member's outstanding
-- (eligible) integration steps, so the Saturday reminder can show "completed since last week"
-- and congratulate progress. Written by the weekly job via the postgres role (bypasses RLS);
-- not client-facing. Additive + idempotent.

create table if not exists reminder_snapshots (
  id         uuid primary key default gen_random_uuid(),
  stake_id   uuid not null references stakes(id) on delete cascade,
  snapshot   jsonb not null,            -- { person_uuid: [missing-step labels] }
  created_at timestamptz not null default now()
);
create index if not exists reminder_snapshots_recent on reminder_snapshots (stake_id, created_at desc);

alter table reminder_snapshots enable row level security;  -- job uses postgres role; no client policies
