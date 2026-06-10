// Mirrors apps/viewer/test/golden_hour_test.dart — pure-logic tests for the Golden Hour milestones,
// the single source of truth the dashboard, person detail, and completion stats all read.

import { describe, it, expect } from 'vitest';
import {
  milestones, milestonesFor, responsibleOrg, completionOf, priesthoodEligible, callingEligible,
  aaronicEligible, endowmentEligible, templeExperienceValue, templeExperienceDisplay,
  type OrgBucket,
} from '../logic/milestones';
import type { Member } from '../lib/member';

function member(over: Partial<Record<string, string>> = {}): Member {
  return {
    friends: 'No',
    calling: 'No',
    ministering_brothers_sisters: 'No',
    ministering_assignment: 'No',
    baptism_date: '',
    temple_recommend: 'No',
    patriarchal_blessing: 'No',
    living_ordinance: 'No',
    aaronic_priesthood: 'N/A',
    melchizedek_priesthood: 'N/A',
    family_name_prepared: 'No',
    first_temple_visit: 'No',
    sex: 'F',
    birth_date: '1 Jan 1990',
    ...over,
  };
}

const thisYear = new Date().getFullYear();
const abbrs = (m: Member) => new Set(milestonesFor(m).map((x) => x.abbr));

describe('milestone predicates', () => {
  it('friends Yes is complete, No is not', () => {
    const f = milestones.find((m) => m.abbr === 'F')!;
    expect(f.complete(member({ friends: 'Yes' }))).toBe(true);
    expect(f.complete(member({ friends: 'No' }))).toBe(false);
  });

  it('baptism is NOT a Golden Hour milestone (integration only)', () => {
    expect(milestones.some((m) => m.abbr === 'B')).toBe(false);
    expect(milestones.some((m) => m.label === 'Baptized')).toBe(false);
  });

  it('milestones are the integration set', () => {
    expect(new Set(milestones.map((m) => m.abbr)))
      .toEqual(new Set(['F', 'C', 'M', 'MA', 'AP', 'MP', 'FN', 'FT']));
  });
});

describe('temple experiences (family name + first temple visit)', () => {
  it('flat column wins; sentinel/empty falls back to details.templeExperiences', () => {
    expect(templeExperienceValue(member({ first_temple_visit: 'Yes' }), 'first_temple_visit')).toBe('Yes');
    const fallback: Member = {
      ...member({ first_temple_visit: 'needs-profile-api', family_name_prepared: 'needs-profile-api' }),
      details: {
        templeExperiences: [
          { name: 'Prepare a Family Name for the Temple', done: false },
          { name: 'Perform Baptisms for Deceased Ancestors', done: true },
        ],
      },
    };
    expect(templeExperienceValue(fallback, 'first_temple_visit')).toBe('Yes');
    expect(templeExperienceValue(fallback, 'family_name_prepared')).toBe('No');
  });

  it('eligible from the year someone turns 12 (by-year rule), like calling', () => {
    const turning12 = member({ birth_date: `1 Jan ${thisYear - 12}` });
    const child = member({ birth_date: `1 Jan ${thisYear - 8}` });
    expect(abbrs(turning12).has('FN')).toBe(true);
    expect(abbrs(turning12).has('FT')).toBe(true);
    expect(abbrs(child).has('FN')).toBe(false);
    expect(abbrs(child).has('FT')).toBe(false);
  });

  it('display gates an ineligible "No" to N/A but keeps a real "Yes"', () => {
    const child = member({ birth_date: `1 Jan ${thisYear - 8}` });
    expect(templeExperienceDisplay(child, 'first_temple_visit')).toBe('N/A');
    const childDone = member({ birth_date: `1 Jan ${thisYear - 8}`, first_temple_visit: 'Yes' });
    expect(templeExperienceDisplay(childDone, 'first_temple_visit')).toBe('Yes');
  });
});

describe('milestonesFor (eligibility filtering)', () => {
  it('priesthood chips only apply to males', () => {
    const aF = abbrs(member({ sex: 'F' }));
    const aM = abbrs(member({ sex: 'M', baptism_date: '1 Jan 2000' }));
    expect(aF.has('AP')).toBe(false);
    expect(aF.has('MP')).toBe(false);
    expect(aM.has('AP')).toBe(true);
    expect(aM.has('MP')).toBe(true);
  });

  it('a young child only has the everyone milestones (friends, has-ministers)', () => {
    const child = member({ sex: 'M', birth_date: `1 Jan ${thisYear - 8}` });
    expect(abbrs(child)).toEqual(new Set(['F', 'M']));
  });

  it('a 12-year-old is eligible for calling + Aaronic, but NOT ministering (needs 14)', () => {
    const turning12 = member({ sex: 'M', birth_date: `1 Jan ${thisYear - 12}` });
    const a = abbrs(turning12);
    expect(a.has('C')).toBe(true);
    expect(a.has('AP')).toBe(true);
    expect(a.has('MA')).toBe(false);
    expect(a.has('MP')).toBe(false);
  });

  it('a 14-year-old is eligible to give ministering', () => {
    const turning14 = member({ sex: 'F', birth_date: `1 Jan ${thisYear - 14}` });
    expect(abbrs(turning14).has('MA')).toBe(true);
  });

  it('Melchizedek needs age 18 NOW AND 1+ year of membership', () => {
    const newAdult = member({ sex: 'M', baptism_date: `1 Jan ${thisYear}` }); // <1yr member
    expect(abbrs(newAdult).has('MP')).toBe(false);
    // turns 18 this year but not 18 yet (born late this-year-minus-18) -> not eligible
    const turning18 = member({ sex: 'M', baptism_date: '1 Jan 2000', birth_date: `31 Dec ${thisYear - 18}` });
    expect(abbrs(turning18).has('MP')).toBe(false);
  });
});

it('a fully-integrated member completes all applicable milestones', () => {
  const m = member({
    friends: 'Yes', calling: 'Yes', ministering_brothers_sisters: 'Yes', ministering_assignment: 'Yes',
    baptism_date: '1 Jan 2000', aaronic_priesthood: 'Yes', melchizedek_priesthood: 'Yes', sex: 'M',
    family_name_prepared: 'Yes', first_temple_visit: 'Yes',
  });
  const applicable = milestonesFor(m);
  expect(applicable.filter((x) => x.complete(m)).length).toBe(applicable.length);
});

describe('responsibleOrg (convert-care ownership by tenure)', () => {
  it('no baptism date → null (Unassigned)', () => {
    expect(responsibleOrg(member())).toBeNull();
  });

  it('first year → missionaries / WML', () => {
    const recent = new Date();
    recent.setMonth(recent.getMonth() - 3);
    const iso = recent.toISOString().slice(0, 10);
    expect(responsibleOrg(member({ baptism_date: iso, sex: 'M' }))).toBe<OrgBucket>('wml');
  });

  it('after a year → EQ (men) / RS (women)', () => {
    expect(responsibleOrg(member({ baptism_date: '1 Jan 2000', sex: 'M' }))).toBe<OrgBucket>('eq');
    expect(responsibleOrg(member({ baptism_date: '1 Jan 2000', sex: 'F' }))).toBe<OrgBucket>('rs');
  });
});

describe('completionOf (detail-page ring) + detail eligibility gates', () => {
  it('0 when nothing applicable is done, 1.0 when all applicable are done (→ green)', () => {
    const none = member({ sex: 'F', baptism_date: '1 Jan 2000' });
    expect(completionOf(none)).toBe(0);
    // F adult, 1yr member: applicable = Friends, Calling, Has-ministers, Ministering-assignment.
    const allDone = member({
      sex: 'F', baptism_date: '1 Jan 2000', friends: 'Yes', calling: 'Yes',
      ministering_brothers_sisters: 'Yes', ministering_assignment: 'Yes',
      family_name_prepared: 'Yes', first_temple_visit: 'Yes',
    });
    expect(completionOf(allDone)).toBe(1);
  });

  it('is a fraction in between for partial completion', () => {
    const half = member({ sex: 'F', baptism_date: '1 Jan 2000', friends: 'Yes', ministering_brothers_sisters: 'Yes' });
    const c = completionOf(half);
    expect(c).toBeGreaterThan(0);
    expect(c).toBeLessThan(1);
  });

  it('priesthood section gated to males; calling gated to age 12+', () => {
    expect(priesthoodEligible(member({ sex: 'F' }))).toBe(false);
    expect(priesthoodEligible(member({ sex: 'M', birth_date: `1 Jan ${thisYear - 20}` }))).toBe(true);
    expect(callingEligible(member({ birth_date: `1 Jan ${thisYear - 8}` }))).toBe(false);
    expect(callingEligible(member({ birth_date: `1 Jan ${thisYear - 12}` }))).toBe(true);
  });

  it('aaronic = male & 12+; endowment = 18+ & 1yr member', () => {
    expect(aaronicEligible(member({ sex: 'F', birth_date: `1 Jan ${thisYear - 20}` }))).toBe(false);
    expect(aaronicEligible(member({ sex: 'M', birth_date: `1 Jan ${thisYear - 14}` }))).toBe(true);
    expect(endowmentEligible(member({ birth_date: `1 Jan ${thisYear - 30}`, baptism_date: '1 Jan 2000' }))).toBe(true);
    expect(endowmentEligible(member({ birth_date: `1 Jan ${thisYear - 30}`, baptism_date: `1 Jan ${thisYear}` }))).toBe(false);
  });
});
