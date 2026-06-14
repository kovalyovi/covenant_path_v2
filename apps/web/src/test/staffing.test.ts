import { describe, it, expect } from 'vitest';
import { staffingGaps, gapCount, type StaffingMember } from '../logic/staffing';

describe('staffingGaps (#12 leadership/staffing gaps)', () => {
  it('flags filled vs gap required roles, with holder names', () => {
    const roster: StaffingMember[] = [
      { position: 'Ward Mission Leader', person: 'A' },
      { position: 'Ward Missionary', person: 'B' },
      { position: 'Ward Missionary', person: 'C' },
      { position: 'Elders Quorum President', person: 'D' },
      { position: 'Relief Society First Counselor', person: 'E' }, // no RS president
      { position: 'Assistant Ward Mission Leader', person: 'F' }, // not the WML
    ];
    const by = Object.fromEntries(staffingGaps(roster).map((r) => [r.key, r]));
    expect(by.wml.ok).toBe(true);
    expect(by.wml.holders).toEqual(['A']);
    expect(by.ward_missionaries.have).toBe(2);
    expect(by.ward_missionaries.ok).toBe(true);
    expect(by.eq_pres.ok).toBe(true);
    expect(by.rs_pres.ok).toBe(false); // only a counselor, no president
    expect(by.rs_pres.have).toBe(0);
  });

  it('an assistant WML is not the WML; 1 of 2 missionaries is a gap', () => {
    const thin: StaffingMember[] = [
      { position: 'Assistant Ward Mission Leader', person: 'F' },
      { position: 'Ward Missionary', person: 'B' },
    ];
    const by = Object.fromEntries(staffingGaps(thin).map((r) => [r.key, r]));
    expect(by.wml.ok).toBe(false);
    expect(by.ward_missionaries.ok).toBe(false);
    expect(gapCount(thin)).toBe(4); // wml, ward_missionaries, eq, rs all unmet
  });

  it('a fully-staffed unit has zero gaps', () => {
    const full: StaffingMember[] = [
      { position: 'Ward Mission Leader', person: 'A' },
      { position: 'Ward Missionary', person: 'B' },
      { position: 'Ward Missionary', person: 'C' },
      { position: 'Elders Quorum President', person: 'D' },
      { position: 'Relief Society President', person: 'E' },
    ];
    expect(gapCount(full)).toBe(0);
  });
});
