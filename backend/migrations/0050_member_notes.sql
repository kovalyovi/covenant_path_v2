-- 0050: ONE editable leader note per member (replaces the member_comments thread model in the UI).
-- Additive + idempotent.
--
-- WHY (item 8): the thread/multi-comment model (member_comments) is being dropped from the UI in favor
-- of a SINGLE editable note per member, shown in full on the main screen and edited inline (no separate
-- "Edit" button). This table holds that single note (one row per member, upserted on edit). The legacy
-- member_comments rows are KEPT (data preserved) and folded into the editable note on first read by the
-- client, then written back here. This durable single note is also what the friends/merge feature
-- (item 11) preserves when a manual record merges with a real one.
--
-- RLS mirrors member_comments / members EXACTLY: stake-wide for stake leaders, the member's unit for
-- ward leaders. A note is bound to a real member in the claimed (stake, unit) — same DBRLS-04 guard.
--
-- Apply with: python -m backend.apply

create table if not exists member_notes (
  id                 uuid primary key default gen_random_uuid(),
  stake_id           uuid not null references stakes(id) on delete cascade,
  unit_id            uuid references units(id) on delete set null,
  member_person_uuid text not null,                         -- members.person_uuid
  note               text not null default '',
  updated_by         text,                                  -- last editor's email
  updated_at         timestamptz not null default now(),
  unique (stake_id, member_person_uuid)                     -- ONE note per member per stake
);
create index if not exists member_notes_lookup
  on member_notes (stake_id, member_person_uuid);

alter table member_notes enable row level security;

drop policy if exists member_notes_select on member_notes;
create policy member_notes_select on member_notes for select using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = member_notes.stake_id
      and (ur.unit_id is null or ur.unit_id = member_notes.unit_id)));

-- INSERT + UPDATE (upsert): the editor must be in scope AND the note must reference a member that
-- actually lives in the claimed (stake, unit) — the same DBRLS-04 bind member_comments uses.
drop policy if exists member_notes_insert on member_notes;
create policy member_notes_insert on member_notes for insert with check (
  (updated_by is null or lower(updated_by) = lower(nullif(auth.jwt() ->> 'email', '')))
  and exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = member_notes.stake_id
      and (ur.unit_id is null or ur.unit_id = member_notes.unit_id))
  and exists (select 1 from members m
    where m.person_uuid = member_notes.member_person_uuid
      and m.stake_id = member_notes.stake_id
      and (member_notes.unit_id is null or m.unit_id = member_notes.unit_id)));

drop policy if exists member_notes_update on member_notes;
create policy member_notes_update on member_notes for update using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = member_notes.stake_id
      and (ur.unit_id is null or ur.unit_id = member_notes.unit_id)))
with check (
  (updated_by is null or lower(updated_by) = lower(nullif(auth.jwt() ->> 'email', '')))
  and exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = member_notes.stake_id
      and (ur.unit_id is null or ur.unit_id = member_notes.unit_id)));

grant select, insert, update on member_notes to authenticated;
grant all on member_notes to service_role;

notify pgrst, 'reload schema';
