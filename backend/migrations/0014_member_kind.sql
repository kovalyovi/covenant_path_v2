-- Distinguish the two covenant-path populations the one-work progress-record returns:
--   'new_member'  — already baptized (milestone tracking)
--   'investigator' — being taught; has a PLANNED future baptism date (baptismGoalDateString)
--   'returning'    — returning member
-- and store the planned baptism goal date separately from the actual baptism date. The app
-- shows investigators' planned dates as "prospective baptisms". Additive + idempotent.

alter table members add column if not exists kind              text default 'new_member';
alter table members add column if not exists baptism_goal_date text;
