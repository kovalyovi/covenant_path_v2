-- 0059: per-stake missionary transfer schedule. Additive + idempotent.
--
-- WHY: the mission runs on a ~6-week transfer cycle (Ricky's Mission-KPIs app tracks the dates). The
-- Baptisms page shows a "next transfer is in N days (date)" banner, and ward baptism goals (0060) are
-- keyed per transfer cycle. Stored PER STAKE (each stake owns its schedule, RLS-scoped like every table)
-- rather than globally — a stake could be in a different mission; a new stake simply starts empty.
--
-- transfer_id is a stable text key (e.g. 't-2026-07-23') so ward_goals can reference a cycle without a
-- FK to a mutable date. RLS: any leader in the stake can READ the schedule (the banner shows for
-- everyone); only STAKE leaders (user_roles.unit_id is null) can add/adjust it — it's a stake/mission
-- concept, not a per-ward one.
--
-- Apply with: python -m backend.apply

create table if not exists transfer_dates (
  id            uuid primary key default gen_random_uuid(),
  stake_id      uuid not null references stakes(id) on delete cascade,
  transfer_id   text not null,                 -- stable cycle key, e.g. 't-2026-07-23'
  transfer_date date not null,
  updated_by    text,                          -- email of the leader who last edited
  updated_at    timestamptz not null default now(),
  unique (stake_id, transfer_id)
);
create index if not exists transfer_dates_lookup on transfer_dates (stake_id, transfer_date);

alter table transfer_dates enable row level security;

-- SELECT: any role in the stake (stake- or ward-level) — the banner shows for everyone.
drop policy if exists transfer_dates_select on transfer_dates;
create policy transfer_dates_select on transfer_dates for select using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = transfer_dates.stake_id));

-- INSERT / UPDATE / DELETE: STAKE leaders only (unit_id is null) — the schedule is stake/mission-wide.
drop policy if exists transfer_dates_insert on transfer_dates;
create policy transfer_dates_insert on transfer_dates for insert with check (
  (updated_by is null or lower(updated_by) = lower(nullif(auth.jwt() ->> 'email', '')))
  and exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = transfer_dates.stake_id and ur.unit_id is null));

drop policy if exists transfer_dates_update on transfer_dates;
create policy transfer_dates_update on transfer_dates for update using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = transfer_dates.stake_id and ur.unit_id is null))
with check (
  (updated_by is null or lower(updated_by) = lower(nullif(auth.jwt() ->> 'email', '')))
  and exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = transfer_dates.stake_id and ur.unit_id is null));

drop policy if exists transfer_dates_delete on transfer_dates;
create policy transfer_dates_delete on transfer_dates for delete using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = transfer_dates.stake_id and ur.unit_id is null));

grant select, insert, update, delete on transfer_dates to authenticated;
grant all on transfer_dates to service_role;

notify pgrst, 'reload schema';
