-- 0064: in-app feedback in ONE place, with an addressed/not state.
--
-- Feedback already became a GitHub issue (#58, admin.create_feedback_issue), but that's the only
-- place it lived: an admin had to go to GitHub to see what people had reported, there was no
-- "have we dealt with this?" state inside the app, and the reporter never heard back. Nothing told
-- the owner a new report had arrived either.
--
-- So mirror every report here: the admin console lists them, flips one to `addressed` (which sends
-- the reporter a thank-you), and the owner gets an email the moment one is filed. The GitHub issue
-- stays the work item -- this table is the inbox and the audit trail.
--
-- PRIVACY: holds the reporter's email + free text -> admin-only by RLS, exactly like login_audit
-- (0033). The broker writes it with the service-role key (which bypasses RLS).
-- Additive + idempotent.

create table if not exists app_feedback (
    id             bigint generated always as identity primary key,
    at             timestamptz not null default now(),
    reporter_email text,                       -- the signed-in user who filed it (lowercased)
    title          text not null,
    body           text,
    issue_number   integer,                    -- the GitHub issue we opened, when GitHub is configured
    issue_url      text,
    status         text not null default 'open',   -- 'open' | 'addressed'
    addressed_at   timestamptz,
    addressed_by   text,                       -- the admin who marked it
    addressed_note text,                       -- what was done (included in the thank-you email)
    thanked_at     timestamptz                 -- when the reporter's thank-you actually sent
);

alter table app_feedback enable row level security;
-- RLS needs a base grant to even evaluate the policy; the policy then restricts SELECT to admins.
grant select on app_feedback to anon, authenticated;
grant select, insert, update on app_feedback to service_role;

drop policy if exists app_feedback_select on app_feedback;
create policy app_feedback_select on app_feedback for select using (is_admin());

create index if not exists app_feedback_at_idx on app_feedback (at desc);
create index if not exists app_feedback_status_idx on app_feedback (status, at desc);

comment on table app_feedback is
  'In-app feedback inbox (0064): one row per report, mirrored to a GitHub issue. status open|addressed; '
  'marking addressed emails the reporter a thank-you. Admin-only by RLS -- holds reporter email + free text.';

notify pgrst, 'reload schema';
