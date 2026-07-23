// Ward-goal logic: which transfer cycle goals apply to now, and per-unit goal vs actual (baptized in
// the cycle window).

import { describe, it, expect } from 'vitest';
import { currentCycle, goalRows, unitOptions, type WardGoal } from '../logic/wardGoals';
import type { TransferDate } from '../logic/transfers';
import type { Member } from '../lib/member';

const SCHEDULE: TransferDate[] = [
  { transfer_id: 't-2026-06-11', transfer_date: '2026-06-11' },
  { transfer_id: 't-2026-07-23', transfer_date: '2026-07-23' },
  { transfer_id: 't-2026-09-03', transfer_date: '2026-09-03' },
];

function member(over: Partial<Record<string, unknown>> = {}): Member {
  return { person_uuid: 'p', name: 'X', unit_name: 'Alpha Ward', unit_id: 'ua', kind: 'new_member', ...over };
}

describe('currentCycle', () => {
  it('is the next upcoming transfer (the cycle it ends)', () => {
    const c = currentCycle(SCHEDULE, new Date(2026, 6, 20)); // Jul 20 → next is Jul 23
    expect(c?.transferId).toBe('t-2026-07-23');
    expect(c?.window.start?.getTime()).toBe(new Date(2026, 5, 11).getTime());
    expect(c?.window.end.getTime()).toBe(new Date(2026, 6, 23).getTime());
  });

  it('falls back to the latest transfer when none is scheduled ahead', () => {
    const c = currentCycle(SCHEDULE, new Date(2026, 11, 1)); // after all
    expect(c?.transferId).toBe('t-2026-09-03');
  });

  it('is null with no schedule', () => {
    expect(currentCycle([], new Date(2026, 6, 20))).toBeNull();
  });
});

describe('goalRows', () => {
  const units = [
    { id: 'ua', name: 'Alpha Ward' },
    { id: 'ub', name: 'Beta Ward' },
  ];
  const goals: WardGoal[] = [
    { unit_id: 'ua', transfer_id: 't-2026-07-23', goal: 3 },
    { unit_id: 'ua', transfer_id: 't-2026-09-03', goal: 9 }, // other cycle — ignored
  ];
  const cycle = currentCycle(SCHEDULE, new Date(2026, 6, 20))!; // t-2026-07-23, (Jun 11, Jul 23]

  it('matches the goal for the unit + cycle, null when unset', () => {
    const rows = goalRows(units, [], goals, cycle.transferId, cycle.window);
    expect(rows.find((r) => r.unitName === 'Alpha Ward')?.goal).toBe(3);
    expect(rows.find((r) => r.unitName === 'Beta Ward')?.goal).toBeNull();
  });

  it('counts baptized members whose baptism_date is inside the cycle window', () => {
    const baptized = [
      member({ unit_name: 'Alpha Ward', baptism_date: '2026-07-01' }), // in window
      member({ unit_name: 'Alpha Ward', baptism_date: '2026-07-23' }), // on end day — counts
      member({ unit_name: 'Alpha Ward', baptism_date: '2026-06-11' }), // on prev transfer — prior cycle
      member({ unit_name: 'Alpha Ward', baptism_date: '2026-08-01' }), // after end
      member({ unit_name: 'Beta Ward', baptism_date: '2026-07-10' }), // other unit
    ];
    const rows = goalRows(units, baptized, goals, cycle.transferId, cycle.window);
    expect(rows.find((r) => r.unitName === 'Alpha Ward')?.actual).toBe(2);
    expect(rows.find((r) => r.unitName === 'Beta Ward')?.actual).toBe(1);
  });

  it('sorts by unit name', () => {
    const rows = goalRows([units[1], units[0]], [], goals, cycle.transferId, cycle.window);
    expect(rows.map((r) => r.unitName)).toEqual(['Alpha Ward', 'Beta Ward']);
  });
});

describe('unitOptions', () => {
  it('de-dupes distinct units by id, sorted by name', () => {
    const members = [
      member({ unit_id: 'ub', unit_name: 'Beta Ward' }),
      member({ unit_id: 'ua', unit_name: 'Alpha Ward' }),
      member({ unit_id: 'ua', unit_name: 'Alpha Ward' }),
    ];
    expect(unitOptions(members).map((u) => u.name)).toEqual(['Alpha Ward', 'Beta Ward']);
  });
});
