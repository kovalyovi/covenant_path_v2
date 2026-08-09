-- Phantom "stake" rows for wards/branches — the DB backstop (2026-08-08).
--
-- Migration 0052 taught the ENROLL RPC to refuse a ward/branch masquerading as a stake, but plain
-- `insert into stakes` was still wide open. Any code path that starts from a LIVE user_context could
-- therefore mint a phantom stake: between 2026-07-22 and 2026-07-26 the LCR probe's operator login
-- resolved to a WARD context, and backend/probe.py called db.upsert_stake() with it. That created
-- `stakes(unit_number = 1102966, name = 'Green Level Ward')` — 0 members, no credential, never
-- synced, 27 orphan probe-diagnostics rows — which then showed up in the admin console's
-- enrolled-stakes list alongside the three real stakes. (The real Green Level Ward has always been a
-- correct `units` row under Raleigh North Carolina West Stake; only the duplicate is bogus.)
--
-- backend/db.upsert_stake now raises SubUnitAsStakeError before writing. This trigger is the
-- belt-and-braces layer that covers every OTHER writer, present and future — the same posture as the
-- 0052 RPC guard. Additive + idempotent.

create or replace function reject_subunit_stake() returns trigger
language plpgsql
as $$
declare
    v_parent text;
begin
    -- Is this unit_number already known as a WARD/BRANCH belonging to some OTHER stake? The
    -- `is distinct from NEW.id` arm keeps a legitimate rename of an existing stake working even if
    -- bad data ever pointed a units row at the stake itself.
    select s.name into v_parent
      from units u
      join stakes s on s.id = u.stake_id
     where u.unit_number = NEW.unit_number
       and upper(coalesce(u.unit_type, '')) in ('WARD', 'BRANCH')
       and u.stake_id is distinct from NEW.id
     limit 1;
    if v_parent is not null then
        raise exception 'unit % is a ward/branch of stake "%" and cannot be stored as a stake; a '
                        'ward leader sees their unit via their ward_leader role',
                        NEW.unit_number, v_parent
            using errcode = 'check_violation';
    end if;
    return NEW;
end;
$$;

drop trigger if exists stakes_reject_subunit on stakes;
create trigger stakes_reject_subunit
    before insert or update of unit_number on stakes
    for each row execute function reject_subunit_stake();

-- ---------------------------------------------------------------------------------------------------
-- Clean up the phantoms already on file. Deliberately narrow: a row only qualifies when the SAME
-- unit_number is already a WARD/BRANCH of a DIFFERENT stake, AND it has no credential, no members and
-- no units of its own — i.e. it can only be the accidental duplicate, never a real stake. Dependent
-- rows (sync_diagnostics, settings, …) all cascade.
delete from stakes s
 where exists (select 1 from units u
                where u.unit_number = s.unit_number
                  and upper(coalesce(u.unit_type, '')) in ('WARD', 'BRANCH')
                  and u.stake_id <> s.id)
   and not exists (select 1 from stake_credentials c where c.stake_id = s.id)
   and not exists (select 1 from members m where m.stake_id = s.id)
   and not exists (select 1 from units u2 where u2.stake_id = s.id);
