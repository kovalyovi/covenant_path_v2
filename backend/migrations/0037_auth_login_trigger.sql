-- Capture EVERY login in login_audit — including DIRECT email-OTP / passkey / Google logins that go
-- browser→Supabase and bypass the broker (which only audits Church + relay logins). A trigger on
-- auth.users fires when last_sign_in_at advances.
--
-- BULLETPROOF: the whole body is wrapped in a sub-block that swallows ALL errors, so it can NEVER
-- abort an auth write — observability must never break a login. Dedups against any login_audit row
-- in the last 2 minutes (so a broker-written Church/relay login isn't double-counted). Idempotent.

create or replace function _on_auth_login() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  begin
    if new.last_sign_in_at is distinct from old.last_sign_in_at and new.last_sign_in_at is not null
       and not exists (select 1 from login_audit la
                       where lower(la.email) = lower(new.email) and la.at > now() - interval '2 minutes') then
      insert into login_audit (email, authorized, outcome, role_scope, request_id)
      values (
        lower(new.email), 'allowed', 'allowed',
        coalesce((select string_agg(role || '×' || cnt, ', ' order by role)
                  from (select role, count(*) cnt from user_roles
                        where lower(email) = lower(new.email) group by role) q), 'none'),
        'supabase-auth');
    end if;
  exception when others then
    null;  -- NEVER let auditing block or slow a login
  end;
  return new;
end; $$;

drop trigger if exists on_auth_login on auth.users;
create trigger on_auth_login after update on auth.users
  for each row execute function _on_auth_login();
