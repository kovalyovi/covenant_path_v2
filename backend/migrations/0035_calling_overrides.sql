-- Admin-editable calling→access overrides (#3c "map it + add new"): grant member-data access to a
-- calling the LCR menu matrix doesn't cover (or that isn't on the always-allowed list) WITHOUT a
-- code deploy. provision_roles unions these in next sync. Admin-managed (RLS admin-only select;
-- add/remove via SECURITY DEFINER RPCs). The static lists remain documented in docs/ACCESS_MODEL.md.

create table if not exists calling_access_overrides (
    id            bigint generated always as identity primary key,
    calling_match text not null,          -- case-insensitive substring matched against the calling name
    grants_access boolean not null default true,
    note          text,
    created_by    text,                    -- admin email who added it
    created_at    timestamptz not null default now(),
    unique (calling_match)
);

alter table calling_access_overrides enable row level security;
grant select on calling_access_overrides to anon, authenticated;   -- RLS policy restricts to admins
grant select on calling_access_overrides to service_role;          -- provisioning reads it
drop policy if exists cao_select on calling_access_overrides;
create policy cao_select on calling_access_overrides for select using (is_admin());

-- Add / update an override (admin-gated). Idempotent on calling_match.
create or replace function add_calling_override(p_match text, p_grants boolean, p_note text)
returns void language plpgsql security definer set search_path = public as $$
begin
    if not is_admin() then raise exception 'not authorized'; end if;
    if p_match is null or btrim(p_match) = '' then raise exception 'calling_match required'; end if;
    insert into calling_access_overrides (calling_match, grants_access, note, created_by)
    values (btrim(p_match), coalesce(p_grants, true), p_note, _jwt_email())
    on conflict (calling_match) do update
        set grants_access = excluded.grants_access, note = excluded.note,
            created_by = excluded.created_by;
end; $$;
grant execute on function add_calling_override(text, boolean, text) to authenticated;

create or replace function remove_calling_override(p_id bigint)
returns void language plpgsql security definer set search_path = public as $$
begin
    if not is_admin() then raise exception 'not authorized'; end if;
    delete from calling_access_overrides where id = p_id;
end; $$;
grant execute on function remove_calling_override(bigint) to authenticated;
