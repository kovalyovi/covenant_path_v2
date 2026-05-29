-- Responsibility-handoff pings (#72): converts transition from missionary / ward-mission-leader
-- fellowship to Elders Quorum (men) / Relief Society (women) at set months post-baptism (6, 12).
-- This table records which (person, phase) handoffs have already been notified, so the weekly job
-- pings each transition exactly once (idempotent across reruns). Internal — written/read only by
-- the scraper/mailer over the DB URL (postgres role); RLS on with no policy denies API roles.
-- Additive + idempotent.

create table if not exists handoff_pings (
    stake_id    uuid not null references stakes(id) on delete cascade,
    person_uuid text not null,
    phase       text not null,                 -- e.g. '6mo', '12mo'
    notified_at timestamptz default now(),
    primary key (stake_id, person_uuid, phase)
);

alter table handoff_pings enable row level security;
