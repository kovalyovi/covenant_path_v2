-- 0051: Manually-added people being taught (friends / investigators a leader tracks before LCR has a
-- record). Additive + idempotent.
--
-- WHY (item 11): a leader can add someone being taught to a unit with a name + custom notes, BEFORE
-- that person shows up in the daily LCR/Member Tools sync. These live in their OWN table (NOT the
-- synced `members` table, which the daily sync owns and can full-replace) so a sync never clobbers a
-- manual entry. They surface in the unit's Being-Taught view alongside synced investigators.
--
-- MERGE (suggest, don't auto): when the daily sync later brings a REAL record that matches a manual
-- one (matched by name within the same unit — done CLIENT-side; the server just stores the link), the
-- UI offers a Merge button. Merging replaces the manual record with the remote one (remote is a FULL
-- override) EXCEPT the custom notes, which are preserved (copied into member_notes for the real
-- member). The manual row is then marked merged (soft-delete: `merged_at` + `merged_into_uuid`) so it
-- stops showing but the audit trail / notes link survives.
--
-- RLS mirrors `members` / `member_comments` EXACTLY: stake-wide for stake leaders, the member's unit
-- for ward leaders. Insert/update/delete are scoped the same way.
--
-- Apply with: python -m backend.apply

create table if not exists manual_members (
  id                 uuid primary key default gen_random_uuid(),
  stake_id           uuid not null references stakes(id) on delete cascade,
  unit_id            uuid references units(id) on delete set null,
  unit_name          text,                                  -- denormalized for display + name-match
  name               text not null,
  custom_notes       text not null default '',
  created_by         text,                                  -- email of the leader who added them
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  merged_at          timestamptz,                           -- set when merged into a real member
  merged_into_uuid   text                                   -- the real members.person_uuid it merged to
);
create index if not exists manual_members_lookup
  on manual_members (stake_id, unit_id) where merged_at is null;

alter table manual_members enable row level security;

-- A leader can see/manage manual members only within their scope (same as members).
drop policy if exists manual_members_select on manual_members;
create policy manual_members_select on manual_members for select using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = manual_members.stake_id
      and (ur.unit_id is null or ur.unit_id = manual_members.unit_id)));

drop policy if exists manual_members_insert on manual_members;
create policy manual_members_insert on manual_members for insert with check (
  (created_by is null or lower(created_by) = lower(nullif(auth.jwt() ->> 'email', '')))
  and exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = manual_members.stake_id
      and (ur.unit_id is null or ur.unit_id = manual_members.unit_id)));

drop policy if exists manual_members_update on manual_members;
create policy manual_members_update on manual_members for update using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = manual_members.stake_id
      and (ur.unit_id is null or ur.unit_id = manual_members.unit_id)))
with check (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = manual_members.stake_id
      and (ur.unit_id is null or ur.unit_id = manual_members.unit_id)));

drop policy if exists manual_members_delete on manual_members;
create policy manual_members_delete on manual_members for delete using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = manual_members.stake_id
      and (ur.unit_id is null or ur.unit_id = manual_members.unit_id)));

grant select, insert, update, delete on manual_members to authenticated;
grant all on manual_members to service_role;

notify pgrst, 'reload schema';
