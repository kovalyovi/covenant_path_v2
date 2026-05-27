-- Let invite_power_user optionally grant a NARROWER (ward) scope, not just clone the
-- caller's full scope. A stake leader can thus grant ward_leader access for a specific
-- unit (e.g. onboard a bishop / give a ward's missionaries ward-only access) — a manual
-- path for ward-level access while auto-provisioning of ward leaders is pending (#21).
-- Still escalation-safe: you can only grant within a scope you already hold.

drop function if exists invite_power_user(text);
create or replace function invite_power_user(p_email text, p_unit uuid default null)
returns integer language plpgsql security definer set search_path = public as $$
declare
    caller_email text := _jwt_email();
    caller_uid   uuid := _jwt_uid();
    n integer := 0;
    r record;
    v_stake uuid;
begin
    if p_email is null or btrim(p_email) = '' then raise exception 'email required'; end if;
    p_email := lower(btrim(p_email));

    if p_unit is null then
        -- clone ALL of the caller's roles (their full access)
        for r in select distinct stake_id, unit_id, role from user_roles ur
                 where ur.auth_id = caller_uid or lower(ur.email) = caller_email
        loop
            insert into user_roles (stake_id, unit_id, role, email, source, invited_by_email)
            values (r.stake_id, r.unit_id, r.role, p_email, 'invitation', caller_email)
            on conflict (stake_id, coalesce(unit_id,'00000000-0000-0000-0000-000000000000'::uuid),
                         role, coalesce(lcr_person_uuid, lower(email), ''))
            do update set source='invitation', invited_by_email=excluded.invited_by_email;
            insert into invitations (stake_id, unit_id, role, invited_email, invited_by_email)
            values (r.stake_id, r.unit_id, r.role, p_email, caller_email);
            n := n + 1;
        end loop;
    else
        -- grant ward_leader for a specific unit (caller must cover it)
        select stake_id into v_stake from units where id = p_unit;
        if v_stake is null then raise exception 'unknown unit'; end if;
        if not exists (select 1 from user_roles c
                       where (c.auth_id = caller_uid or lower(c.email) = caller_email)
                         and c.stake_id = v_stake
                         and (c.unit_id is null or c.unit_id = p_unit)) then
            raise exception 'not authorized to grant access to that unit';
        end if;
        insert into user_roles (stake_id, unit_id, role, email, source, invited_by_email)
        values (v_stake, p_unit, 'ward_leader', p_email, 'invitation', caller_email)
        on conflict (stake_id, coalesce(unit_id,'00000000-0000-0000-0000-000000000000'::uuid),
                     role, coalesce(lcr_person_uuid, lower(email), ''))
        do update set source='invitation', invited_by_email=excluded.invited_by_email;
        insert into invitations (stake_id, unit_id, role, invited_email, invited_by_email)
        values (v_stake, p_unit, 'ward_leader', p_email, caller_email);
        n := 1;
    end if;

    if n = 0 then raise exception 'caller has no roles to share'; end if;
    return n;
end; $$;
grant execute on function invite_power_user(text, uuid) to authenticated;
