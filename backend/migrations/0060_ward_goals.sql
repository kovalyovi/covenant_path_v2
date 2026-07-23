-- 0060: per-ward, per-transfer-cycle baptism goal. Additive + idempotent.
--
-- WHY: each ward sets a baptism goal for a transfer cycle (Ricky's Mission-KPIs app tracks these per
-- unit_number + transfer_id). The KPIs page shows goal-vs-actual for the current cycle and lets leaders
-- edit it. Stored per (stake, unit, transfer cycle); `transfer_id` references a `transfer_dates` cycle
-- key (text, no FK — a goal can outlive a re-keyed date). unit_number/unit_name are denormalized for
-- display + Ricky cross-reference.
--
-- RLS mirrors members/manual_members: a stake leader edits any unit's goal, a ward leader only their
-- own unit's. unit_id is required (a goal is always for a specific ward).
--
-- Apply with: python -m backend.apply

create table if not exists ward_goals (
  id           uuid primary key default gen_random_uuid(),
  stake_id     uuid not null references stakes(id) on delete cascade,
  unit_id      uuid not null references units(id) on delete cascade,
  unit_number  int,
  unit_name    text,
  transfer_id  text not null,                  -- the transfer_dates cycle key, e.g. 't-2026-07-23'
  goal         int not null default 0,
  updated_by   text,
  updated_at   timestamptz not null default now(),
  unique (stake_id, unit_id, transfer_id)
);
create index if not exists ward_goals_lookup on ward_goals (stake_id, transfer_id);

alter table ward_goals enable row level security;

drop policy if exists ward_goals_select on ward_goals;
create policy ward_goals_select on ward_goals for select using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = ward_goals.stake_id
      and (ur.unit_id is null or ur.unit_id = ward_goals.unit_id)));

drop policy if exists ward_goals_insert on ward_goals;
create policy ward_goals_insert on ward_goals for insert with check (
  (updated_by is null or lower(updated_by) = lower(nullif(auth.jwt() ->> 'email', '')))
  and exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = ward_goals.stake_id
      and (ur.unit_id is null or ur.unit_id = ward_goals.unit_id)));

drop policy if exists ward_goals_update on ward_goals;
create policy ward_goals_update on ward_goals for update using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = ward_goals.stake_id
      and (ur.unit_id is null or ur.unit_id = ward_goals.unit_id)))
with check (
  (updated_by is null or lower(updated_by) = lower(nullif(auth.jwt() ->> 'email', '')))
  and exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = ward_goals.stake_id
      and (ur.unit_id is null or ur.unit_id = ward_goals.unit_id)));

drop policy if exists ward_goals_delete on ward_goals;
create policy ward_goals_delete on ward_goals for delete using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = ward_goals.stake_id
      and (ur.unit_id is null or ur.unit_id = ward_goals.unit_id)));

grant select, insert, update, delete on ward_goals to authenticated;
grant all on ward_goals to service_role;

notify pgrst, 'reload schema';
