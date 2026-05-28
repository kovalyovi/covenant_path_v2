-- Leader comments on a member. RLS mirrors the members policy exactly (stake-wide for stake
-- leaders, the member's unit for ward leaders), so a user can only read/add comments on people
-- they can already see. Authors can delete their own. Additive + idempotent.

create table if not exists member_comments (
  id                 uuid primary key default gen_random_uuid(),
  stake_id           uuid not null references stakes(id) on delete cascade,
  unit_id            uuid references units(id) on delete set null,
  member_person_uuid text not null,           -- members.person_uuid
  author_email       text not null,
  author_name        text,
  body               text not null,
  created_at         timestamptz not null default now()
);
create index if not exists member_comments_lookup
  on member_comments (stake_id, member_person_uuid, created_at);

alter table member_comments enable row level security;

drop policy if exists member_comments_select on member_comments;
create policy member_comments_select on member_comments for select using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = member_comments.stake_id
      and (ur.unit_id is null or ur.unit_id = member_comments.unit_id)));

drop policy if exists member_comments_insert on member_comments;
create policy member_comments_insert on member_comments for insert with check (
  lower(author_email) = lower(nullif(auth.jwt() ->> 'email', ''))
  and exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = member_comments.stake_id
      and (ur.unit_id is null or ur.unit_id = member_comments.unit_id)));

drop policy if exists member_comments_delete on member_comments;
create policy member_comments_delete on member_comments for delete using (
  lower(author_email) = lower(nullif(auth.jwt() ->> 'email', '')));

grant select, insert, delete on member_comments to authenticated;
grant all on member_comments to service_role;
