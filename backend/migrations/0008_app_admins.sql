-- App admins: an invitable list of people who can see the ops/health console. Mirrors
-- power users (invite-only, auditable) but grants NO data access — only visibility into
-- system health, sync freshness, GitHub Actions, and the ability to kick off maintenance
-- flows. The first admin is seeded; existing admins invite/revoke others.

create table if not exists app_admins (
    email            text primary key,
    invited_by_email text,
    created_at       timestamptz default now()
);
alter table app_admins enable row level security;
grant select on app_admins to anon, authenticated;

-- is_admin(): is the request's verified email in the admin list? (_jwt_email from 0005)
-- SECURITY DEFINER so it bypasses RLS on app_admins — otherwise the app_admins_select
-- policy (which calls is_admin) would recurse infinitely when is_admin reads the table.
create or replace function is_admin() returns boolean language sql stable
security definer set search_path = public as
$$ select exists (select 1 from app_admins a where a.email = _jwt_email()) $$;
grant execute on function is_admin() to anon, authenticated;

-- Only admins can see the admin list.
drop policy if exists app_admins_select on app_admins;
create policy app_admins_select on app_admins for select using (is_admin());

-- Invite another admin (admin-gated). Idempotent.
create or replace function invite_admin(p_email text)
returns void language plpgsql security definer set search_path = public as $$
begin
    if not is_admin() then raise exception 'not authorized'; end if;
    if p_email is null or btrim(p_email) = '' then raise exception 'email required'; end if;
    insert into app_admins (email, invited_by_email)
    values (lower(btrim(p_email)), _jwt_email())
    on conflict (email) do nothing;
end; $$;
grant execute on function invite_admin(text) to authenticated;

-- Revoke an admin (admin-gated; can't revoke yourself, so there's always >=1 admin).
create or replace function revoke_admin(p_email text)
returns void language plpgsql security definer set search_path = public as $$
begin
    if not is_admin() then raise exception 'not authorized'; end if;
    if lower(btrim(p_email)) = _jwt_email() then raise exception 'cannot revoke yourself'; end if;
    delete from app_admins where email = lower(btrim(p_email));
end; $$;
grant execute on function revoke_admin(text) to authenticated;

-- Seed the first admin so invite_admin has a bootstrap caller. Idempotent.
insert into app_admins (email, invited_by_email) values ('ilia.kovaliov@gmail.com', 'system')
on conflict (email) do nothing;
