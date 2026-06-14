-- Notes are a THREAD again (user feedback): multiple timestamped entries per member that unit leaders
-- can add, EDIT, and DELETE (individual + all). The legacy member_comments table (0017) already is the
-- thread (id, author, body, created_at) — this re-enables it for the UI and grants leaders edit/delete
-- on EVERY entry in their scope (not just their own), per "editable/deletable by leaders of those
-- units". member_notes (0050, the single note) is kept for the manual-merge feature's preserved note.
-- Additive + idempotent.

alter table member_comments add column if not exists updated_at timestamptz;
alter table member_comments add column if not exists updated_by text;

-- Scope predicate (same as member_comments_select): a leader of the member's (stake, unit).
-- UPDATE: any in-scope leader can edit any entry (with check keeps it in scope + stamps the editor).
drop policy if exists member_comments_update on member_comments;
create policy member_comments_update on member_comments for update using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = member_comments.stake_id
      and (ur.unit_id is null or ur.unit_id = member_comments.unit_id)))
with check (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = member_comments.stake_id
      and (ur.unit_id is null or ur.unit_id = member_comments.unit_id)));

-- DELETE: was author-only (0017); widen to any in-scope leader so a unit's leaders can remove any
-- entry (individual or all) on a member they oversee.
drop policy if exists member_comments_delete on member_comments;
create policy member_comments_delete on member_comments for delete using (
  exists (select 1 from user_roles ur
    where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email', '')))
      and ur.stake_id = member_comments.stake_id
      and (ur.unit_id is null or ur.unit_id = member_comments.unit_id)));

grant update on member_comments to authenticated;

notify pgrst, 'reload schema';
