-- 0058: notes can be created for a person we haven't synced yet (no more 404), and get adopted into
-- the right stake once that person appears in a sync. Additive + idempotent.
--
-- WHY: the Mission-KPIs partner lane (partner_notes.py) 404'd on add/read when the person had no
-- `members` row. That happens transiently — e.g. the operator's LCR calling changed for a few days, so
-- the daily sync couldn't pull that person, and their `members` row was absent. A leader (Ricky) then
-- can't record a note at all. Notes must be creatable for a bare person_uuid and must SURVIVE until the
-- real record shows up.
--
-- HOW: `member_comments.member_person_uuid` is already a plain text join key (NOT a FK), so a comment
-- can exist without a `members` row. The only blocker was `stake_id NOT NULL` — we don't know the stake
-- for a not-yet-synced person. Drop that NOT NULL so the service-role partner lane can write a "pending"
-- (null-stake) comment; the daily sync then ADOPTS it (db.adopt_orphan_notes: sets stake_id/unit_id from
-- the member once person_uuid matches).
--
-- SAFE: the authenticated INSERT policy (0017) requires `ur.stake_id = member_comments.stake_id`, which
-- is NULL→false for a null-stake row — so a browser user can NEVER create a pending row; only the
-- service-role broker can. Pending rows are invisible to every RLS SELECT (same stake predicate) until
-- adopted, so they never leak cross-stake — they simply wait, then become visible under the right stake.
--
-- Apply with: python -m backend.apply

alter table member_comments alter column stake_id drop not null;

-- Fast lookup of pending (unadopted) comments for the sync's adoption pass.
create index if not exists member_comments_pending
  on member_comments (member_person_uuid) where stake_id is null;

notify pgrst, 'reload schema';
