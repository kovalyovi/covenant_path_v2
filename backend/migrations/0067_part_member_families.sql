-- 0067: Part-member families (Turley / North Carolina Raleigh Mission proposal, Aug 2026):
-- a household where one or more are members and one or more are not — an unbaptized spouse or an
-- unbaptized child age 9+. The stake presidency asked for two LCR lists (unbaptized children 9+ and
-- unbaptized spouses), a Do Not Contact flag before any outreach, and a monthly per-unit rollup.
--
-- WHY its own table (like manual_members, 0051): the daily sync OWNS `members` and can full-replace
-- it, and a part-member non-member has no member record at all (an unbaptized spouse isn't in the
-- directory; an unbaptized child 9+ is a member of record, not a covenant-path person). Leader-entered
-- state (status / Do Not Contact / notes / companionship) must never be clobbered by a sync.
--
-- SOURCES: `lcr_list_a` rows are derived by the daily sync from the Member Tools /api/v5/sync payload
-- (households[].members[].classifications[] contains MEMBER — or an `mrn` — plus
-- unitStatistics[].membersOfRecordAge9OrOlderUuids per unit, else age >= 9; see
-- covenant_path.membertools_adapter.derive_part_member_families, aligned to Ricky Bloomfield's
-- verified Mission-KPIs model). `lcr_list_b` rows are likewise sync-derived (unbaptized adult in
-- the home, or a couple-form listed name naming a spouse who isn't on the roster — see
-- derive_part_member_families_list_b). The sync upserts ONLY the derived columns (household, unit,
-- names, birth date, basis, named_spouse, age_group) and NEVER overwrites status / do_not_contact /
-- notes / assigned_companionship (see backend.db.upsert_part_member_families). `lcr_report`
-- (unbaptized spouses, from the LCR Create Report) and `manual` rows are leader-added.
--
-- PRIVACY: nonmember_birth_date is confidential (age band only is shown in the app) and the stake
-- rollup is unit TOTALS with no names. RLS mirrors `members` / `manual_members` EXACTLY: stake-wide
-- for stake leaders, the family's unit for ward leaders.
--
-- Apply with: python -m backend.apply

create table if not exists part_member_families (
  id                 uuid primary key default gen_random_uuid(),
  stake_id           uuid not null references stakes(id) on delete cascade,
  unit_id            uuid references units(id) on delete set null,
  unit_name          text,                                  -- denormalized for display + grouping
  household_uuid     text,                                  -- Member Tools households[].uuid (List A)
  household_name     text,                                  -- Member Tools households[].name
  member_person_uuid text,                                  -- the MEMBER relative (directory uuid)
  member_name        text,                                  -- denormalized for display
  nonmember_name     text not null,                         -- the unbaptized spouse / child
  nonmember_role     text not null check (nonmember_role in ('spouse', 'child')),
  nonmember_birth_date text,                               -- ISO date when known; confidential
  age_group          text,                                  -- ADULT / YOUTH / CHILD (List A/B derivation)
  basis              text,                                  -- List B evidence grade: unbaptized_spouse_in_home
                                                            -- (confirmed) | spouse_not_on_record (candidate)
  named_spouse       text,                                  -- spouse the couple-form listed name names
  source             text not null default 'manual'
                     check (source in ('lcr_list_a', 'lcr_list_b', 'lcr_report', 'manual')),
  status             text not null default 'identified'
                     check (status in ('identified', 'love', 'share', 'on_date', 'baptized',
                                        'do_not_contact')),
  status_updated_at  timestamptz,                           -- last leader status change
  assigned_companionship text,                             -- missionary companionship (display text)
  do_not_contact_reason text,                              -- why flagged (only when do_not_contact)
  notes              text not null default '',
  created_by         text,                                  -- email of the leader who added / owns it
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  merged_into_uuid   text                                   -- real members.person_uuid when baptized
);
create index if not exists part_member_families_lookup
  on part_member_families (stake_id, unit_id, status);
-- One derived row per (member, non-member, role, source): the sync's ON CONFLICT target. Partial
-- because only derived rows are sync-owned; manual / LCR-report rows may legitimately repeat a name
-- (e.g. a spouse added by hand before the report import lands).
create unique index if not exists part_member_families_lcr_key
  on part_member_families (stake_id, member_person_uuid, nonmember_name, nonmember_role, source)
  where source in ('lcr_list_a', 'lcr_list_b');

alter table part_member_families enable row level security;

-- A leader can see/manage part-member families only within their scope (same as members).
drop policy if exists part_member_families_select on part_member_families;
create policy part_member_families_select on part_member_families for select using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = part_member_families.stake_id
      and (ur.unit_id is null or ur.unit_id = part_member_families.unit_id)));

drop policy if exists part_member_families_insert on part_member_families;
create policy part_member_families_insert on part_member_families for insert with check (
  (created_by is null or lower(created_by) = lower(nullif(auth.jwt() ->> 'email', '')))
  and exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = part_member_families.stake_id
      and (ur.unit_id is null or ur.unit_id = part_member_families.unit_id)));

drop policy if exists part_member_families_update on part_member_families;
create policy part_member_families_update on part_member_families for update using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = part_member_families.stake_id
      and (ur.unit_id is null or ur.unit_id = part_member_families.unit_id)))
with check (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = part_member_families.stake_id
      and (ur.unit_id is null or ur.unit_id = part_member_families.unit_id)));

drop policy if exists part_member_families_delete on part_member_families;
create policy part_member_families_delete on part_member_families for delete using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = part_member_families.stake_id
      and (ur.unit_id is null or ur.unit_id = part_member_families.unit_id)));

grant select, insert, update, delete on part_member_families to authenticated;
grant all on part_member_families to service_role;

notify pgrst, 'reload schema';
