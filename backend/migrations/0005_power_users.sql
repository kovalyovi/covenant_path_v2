-- Power users: any leader can grant their EXACT access to another email (no church
-- account needed — they sign in via Supabase email OTP and RLS matches by email). The
-- invitee gets the same role/scope and can invite further (recursive). You can only
-- CLONE roles you hold, so there's no privilege escalation. Audited + revocable.

-- user_roles can now be sourced from an invitation as well as from a calling. The
-- uniqueness key becomes "subject" = lcr_person_uuid (calling) OR email (invitation),
-- so multiple invited emails can share the same scope.
alter table user_roles add column if not exists source           text default 'calling';
alter table user_roles add column if not exists invited_by_email text;

drop index if exists user_roles_provision_key;
create unique index if not exists user_roles_subject_key on user_roles (
    stake_id,
    coalesce(unit_id, '00000000-0000-0000-0000-000000000000'::uuid),
    role,
    coalesce(lcr_person_uuid, lower(email), '')
);

-- audit + management of invitations
create table if not exists invitations (
    id               uuid primary key default gen_random_uuid(),
    stake_id         uuid not null references stakes(id) on delete cascade,
    unit_id          uuid references units(id) on delete cascade,   -- null = stake-wide
    role             text not null,
    invited_email    text not null,
    invited_by_email text,
    status           text not null default 'pending',  -- pending | active | revoked
    emailed          boolean default false,            -- email queue flag
    created_at       timestamptz default now(),
    revoked_at       timestamptz
);
create index if not exists invitations_stake_idx on invitations(stake_id);
create index if not exists invitations_email_idx on invitations(lower(invited_email));

alter table invitations enable row level security;
grant select on invitations to anon, authenticated;
drop policy if exists invitations_select on invitations;
create policy invitations_select on invitations for select using (
    exists (select 1 from user_roles ur
            where (ur.auth_id = auth.uid() or lower(ur.email) = lower(nullif(auth.jwt() ->> 'email','')))
              and ur.stake_id = invitations.stake_id
              and (ur.unit_id is null or ur.unit_id = invitations.unit_id))
);

-- _jwt_email / _jwt_uid: read the caller's identity from the request JWT (no auth-schema dep).
create or replace function _jwt_email() returns text language sql stable as
$$ select lower(nullif(current_setting('request.jwt.claims', true)::json ->> 'email', '')) $$;
create or replace function _jwt_uid() returns uuid language sql stable as
$$ select nullif(current_setting('request.jwt.claims', true)::json ->> 'sub', '')::uuid $$;

-- Clone ALL of the caller's roles to p_email (their exact access). Returns #scopes granted.
create or replace function invite_power_user(p_email text)
returns integer language plpgsql security definer set search_path = public as $$
declare
    caller_email text := _jwt_email();
    caller_uid   uuid := _jwt_uid();
    n integer := 0;
    r record;
begin
    if p_email is null or btrim(p_email) = '' then raise exception 'email required'; end if;
    p_email := lower(btrim(p_email));
    for r in
        select distinct stake_id, unit_id, role from user_roles ur
        where ur.auth_id = caller_uid or lower(ur.email) = caller_email
    loop
        insert into user_roles (stake_id, unit_id, role, email, source, invited_by_email)
        values (r.stake_id, r.unit_id, r.role, p_email, 'invitation', caller_email)
        on conflict (stake_id, coalesce(unit_id,'00000000-0000-0000-0000-000000000000'::uuid),
                     role, coalesce(lcr_person_uuid, lower(email), ''))
        do update set source = 'invitation', invited_by_email = excluded.invited_by_email;
        insert into invitations (stake_id, unit_id, role, invited_email, invited_by_email)
        values (r.stake_id, r.unit_id, r.role, p_email, caller_email);
        n := n + 1;
    end loop;
    if n = 0 then raise exception 'caller has no roles to share'; end if;
    return n;
end; $$;
grant execute on function invite_power_user(text) to authenticated;

-- Revoke an invited email's access — only within scopes the caller holds.
create or replace function revoke_power_user(p_email text)
returns integer language plpgsql security definer set search_path = public as $$
declare
    caller_email text := _jwt_email();
    caller_uid   uuid := _jwt_uid();
    n integer;
begin
    p_email := lower(btrim(p_email));
    delete from user_roles tgt
    where tgt.source = 'invitation' and lower(tgt.email) = p_email
      and exists (select 1 from user_roles c
                  where (c.auth_id = caller_uid or lower(c.email) = caller_email)
                    and c.stake_id = tgt.stake_id
                    and (c.unit_id is null or c.unit_id = tgt.unit_id));
    get diagnostics n = row_count;
    update invitations i set status = 'revoked', revoked_at = now()
    where lower(i.invited_email) = p_email and i.status <> 'revoked'
      and exists (select 1 from user_roles c
                  where (c.auth_id = caller_uid or lower(c.email) = caller_email)
                    and c.stake_id = i.stake_id
                    and (c.unit_id is null or c.unit_id = i.unit_id));
    return n;
end; $$;
grant execute on function revoke_power_user(text) to authenticated;
