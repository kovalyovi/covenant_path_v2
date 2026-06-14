-- Leadership / staffing per unit (#12). The Member Tools bulk payload carries every unit's callings
-- (households[].members[].positions). We store a compact per-unit roster of the LEADERSHIP-relevant
-- callings on the `units` row so the new Leadership tab can show who's serving and which required
-- positions are GAPS. Stored on `units` (not a new table) ON PURPOSE: the existing `units_select`
-- RLS already scopes it correctly — whole-stake leaders see every unit's staffing, a ward leader sees
-- only their unit's. No new policy, no new grant (0046 covers service_role), no app-side filtering.
--
-- Shape: jsonb array of { position, person, person_uuid, set_apart } for the unit's tracked callings.
-- Additive + idempotent.

alter table units add column if not exists staffing jsonb;

comment on column units.staffing is
  'Per-unit leadership roster from the Member Tools bulk payload (#12): [{position, person, '
  'person_uuid, set_apart}]. RLS via units_select (stake leaders all units; ward leaders their unit).';

-- PostgREST reads the column immediately (no restart) once the schema cache reloads.
notify pgrst, 'reload schema';
