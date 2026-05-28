-- Observability for the LCR pipeline: one row per sync (and per probe-bot run) capturing
-- run stats (units ok/failed), field-coverage parity (which fields came back filled vs
-- blocked vs pending), and per-endpoint request metrics (latency, status histogram, 500s).
-- The admin console reads this via the broker (service-role) to show success %, failing
-- units, parity, and latency over time. Writers use the postgres role (bypasses RLS).
-- Additive + idempotent.

create table if not exists sync_diagnostics (
    id        uuid primary key default gen_random_uuid(),
    stake_id  uuid references stakes(id) on delete cascade,
    kind      text not null default 'sync',   -- 'sync' | 'probe'
    run_at    timestamptz default now(),
    payload   jsonb
);
create index if not exists sync_diag_run_idx on sync_diagnostics (run_at desc);

alter table sync_diagnostics enable row level security;
grant select on sync_diagnostics to service_role;  -- broker (admin console) reads it
