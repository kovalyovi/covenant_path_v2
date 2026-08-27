// Leadership / staffing gap rule (#12). Given a unit's roster of held callings (from the Member Tools
// bulk payload, stored on units.staffing), determine which REQUIRED positions are filled and which are
// gaps — "is there a ward mission leader? at least 2 ward missionaries? an EQ president? an RS
// president?". Pure → mirrored to native. The position strings are the LCR calling names.

export interface StaffingMember {
  position: string;
  person?: string;
  person_uuid?: string;
  set_apart?: boolean;
}

export interface RoleStatus {
  key: string;
  label: string;
  have: number;
  min: number;
  ok: boolean;
  holders: string[]; // names of the people serving in this role (may be empty when unknown)
}

interface RequiredRole {
  key: string;
  label: string;
  min: number;
  match: (position: string) => boolean;
}

/** The roster every unit is expected to have for new-member success to be trackable (#12). Extend here
 *  as leaders ask for more — this is the single definition the gap check + the UI read. */
export const REQUIRED_ROLES: RequiredRole[] = [
  {
    key: 'wml', label: 'Mission leader', min: 1,
    match: (p) => /(ward|branch) mission leader/i.test(p) && !/assistant|asst/i.test(p),
  },
  {
    key: 'ward_missionaries', label: 'Ward/branch missionaries', min: 2,
    match: (p) => /(ward|branch) missionary/i.test(p),
  },
  {
    key: 'eq_pres', label: 'Elders Quorum president', min: 1,
    match: (p) => /elders quorum president/i.test(p) && !/counselor|assistant|secretary|clerk/i.test(p),
  },
  {
    key: 'rs_pres', label: 'Relief Society president', min: 1,
    match: (p) => /relief society president/i.test(p) && !/counselor|assistant|secretary|clerk/i.test(p),
  },
];

/** Per-required-role fill status for a unit's roster — `ok` when at least `min` are serving. */
export function staffingGaps(roster: StaffingMember[]): RoleStatus[] {
  return REQUIRED_ROLES.map((role) => {
    const held = roster.filter((m) => role.match(m.position));
    const holders = held.map((m) => m.person).filter((n): n is string => !!n && n.trim().length > 0);
    return {
      key: role.key,
      label: role.label,
      have: held.length,
      min: role.min,
      ok: held.length >= role.min,
      holders,
    };
  });
}

/** Count of unmet required roles for a unit (0 = fully staffed for the tracked positions). */
export function gapCount(roster: StaffingMember[]): number {
  return staffingGaps(roster).filter((r) => !r.ok).length;
}
