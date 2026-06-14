// Mirrors apps/viewer/test/golden_hour_test.dart — pure-logic tests for the Golden Hour milestones,
// the single source of truth the dashboard, person detail, and completion stats all read.

import { describe, it, expect } from 'vitest';
import {
  milestones, milestonesFor, needsCategories, responsibleOrg, completionOf, priesthoodEligible,
  callingEligible, aaronicEligible, endowmentEligible, templeExperienceValue, templeExperienceDisplay,
  isNA, expected, isMissing, patriarchalEligible, templeRecommendEligible,
  goldenHourRows, nextSteps, unitGoldenHour,
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
    // an eligible male's priesthood reads "No" (not yet ordained), not the N/A fixture default — N/A
    // would be EXCLUDED (item 4b), so eligibility tests use the realistic not-done value.
    const aM = abbrs(member({ sex: 'M', baptism_date: '1 Jan 2000', aaronic_priesthood: 'No', melchizedek_priesthood: 'No' }));
    expect(aF.has('AP')).toBe(false);
    expect(aF.has('MP')).toBe(false);
    expect(aM.has('AP')).toBe(true);
    expect(aM.has('MP')).toBe(true);
  });

  it('a young child only has the everyone milestones (friends, ministers-assigned)', () => {
    const child = member({ sex: 'M', birth_date: `1 Jan ${thisYear - 8}` });
    expect(abbrs(child)).toEqual(new Set(['F', 'M']));
  });

  it('a 12-year-old is eligible for calling + Aaronic, but NOT ministering (needs 14)', () => {
    const turning12 = member({ sex: 'M', birth_date: `1 Jan ${thisYear - 12}`, aaronic_priesthood: 'No' });
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

describe('N/A exclusion + patriarchal/temple-name gate (item 4)', () => {
  const calling = needsCategories.find((m) => m.abbr === 'C')!;
  const aaronic = needsCategories.find((m) => m.abbr === 'AP')!;
  const patriarchal = needsCategories.find((m) => m.abbr === 'PB')!;
  const recommend = needsCategories.find((m) => m.abbr === 'TR')!;

  it('isNA recognizes the N/A sentinel (case/space tolerant)', () => {
    expect(isNA('N/A')).toBe(true);
    expect(isNA(' n/a ')).toBe(true);
    expect(isNA('No')).toBe(false);
    expect(isNA('Yes')).toBe(false);
    expect(isNA(null)).toBe(false);
  });

  it('an N/A field is NOT missing (N/A ≠ not-done) even for an eligible member', () => {
    // An adult man whose calling field is somehow N/A: not expected, not missing.
    const m = member({ sex: 'M', birth_date: `1 Jan ${thisYear - 30}`, calling: 'N/A' });
    expect(expected(calling, m)).toBe(false);
    expect(isMissing(calling, m)).toBe(false);
    // A real not-done IS missing.
    const notDone = member({ sex: 'M', birth_date: `1 Jan ${thisYear - 30}`, calling: 'No' });
    expect(isMissing(calling, notDone)).toBe(true);
  });

  it("priesthood N/A for a woman is excluded (she's not even eligible)", () => {
    const woman = member({ sex: 'F', birth_date: `1 Jan ${thisYear - 30}`, aaronic_priesthood: 'N/A' });
    expect(expected(aaronic, woman)).toBe(false);
    expect(isMissing(aaronic, woman)).toBe(false);
  });

  it('patriarchal blessing uses the SAME age gate as temple recommend (turning ≥12 this year)', () => {
    const child = member({ birth_date: `1 Jan ${thisYear - 8}` });
    const teen = member({ birth_date: `1 Jan ${thisYear - 12}` });
    expect(patriarchalEligible(child)).toBe(templeRecommendEligible(child)); // both false
    expect(patriarchalEligible(teen)).toBe(templeRecommendEligible(teen));   // both true
    expect(patriarchalEligible(teen)).toBe(true);
    expect(patriarchalEligible(child)).toBe(false);
    // a child is therefore never "missing" a patriarchal blessing / temple recommend
    expect(isMissing(patriarchal, member({ birth_date: `1 Jan ${thisYear - 8}`, patriarchal_blessing: 'N/A' }))).toBe(false);
    expect(isMissing(recommend, member({ birth_date: `1 Jan ${thisYear - 8}`, temple_recommend: 'N/A' }))).toBe(false);
  });

  it('completion ring + milestonesFor exclude an N/A milestone from the denominator', () => {
    // adult woman, 1yr member: applicable = Friends, Calling, Ministers-assigned, Ministering-assignment,
    // Family name, First temple visit = 6. If calling is N/A, applicable drops to 5.
    const base = member({ sex: 'F', baptism_date: '1 Jan 2000' });
    expect(milestonesFor(base).length).toBe(6);
    const naCalling = member({ sex: 'F', baptism_date: '1 Jan 2000', calling: 'N/A' });
    expect(milestonesFor(naCalling).length).toBe(5);
    // a completed milestone still counts even if oddly N/A-shaped is irrelevant here; verify ring math
    const oneDone = member({ sex: 'F', baptism_date: '1 Jan 2000', calling: 'N/A', friends: 'Yes' });
    expect(completionOf(oneDone)).toBeCloseTo(1 / 5, 5);
  });
});

describe('goldenHourRows (item 4: one row per item — done / not-done / ⚠ issue, N/A OMITTED)', () => {
  const statusByAbbr = (m: Member, list = milestones) =>
    Object.fromEntries(goldenHourRows(m, list).map((r) => [r.milestone.abbr, r.status]));

  it('OMITS N/A milestones entirely (not eligible — never shown as a row)', () => {
    // A woman: priesthood (AP/MP) is N/A for her — those rows must be ABSENT, not "issue" or "not-done".
    const woman = member({ sex: 'F', baptism_date: '1 Jan 2000', birth_date: `1 Jan ${thisYear - 30}` });
    const abbrsShown = new Set(goldenHourRows(woman).map((r) => r.milestone.abbr));
    expect(abbrsShown.has('AP')).toBe(false);
    expect(abbrsShown.has('MP')).toBe(false);
    // A young child: only the everyone milestones (Friends, Ministers-assigned) — nothing N/A leaks in.
    const child = member({ sex: 'M', birth_date: `1 Jan ${thisYear - 8}` });
    expect(new Set(goldenHourRows(child).map((r) => r.milestone.abbr))).toEqual(new Set(['F', 'M']));
  });

  it('a completed milestone is "done"', () => {
    const m = member({ friends: 'Yes' });
    expect(statusByAbbr(m)['F']).toBe('done');
  });

  it('a real recorded "No" is "not-done" (an honest not-done, NOT a data issue)', () => {
    const m = member({ friends: 'No' });
    expect(statusByAbbr(m)['F']).toBe('not-done');
  });

  it('the needs-profile-api sentinel renders as a ⚠ DATA ISSUE row, not not-done', () => {
    // calling is eligible (adult), but its value is the sentinel → an "issue" row (we should know it).
    const m = member({ sex: 'M', birth_date: `1 Jan ${thisYear - 30}`, baptism_date: '1 Jan 2000', calling: 'needs-profile-api' });
    expect(statusByAbbr(m)['C']).toBe('issue');
  });

  it('an empty/missing value is also a ⚠ data issue (treated the same as the sentinel)', () => {
    const m = member({ sex: 'M', birth_date: `1 Jan ${thisYear - 30}`, baptism_date: '1 Jan 2000', calling: '' });
    expect(statusByAbbr(m)['C']).toBe('issue');
  });

  it('includes the longer-horizon covenants when given needsCategories', () => {
    const m = member({
      sex: 'M', baptism_date: '1 Jan 2000', birth_date: `1 Jan ${thisYear - 40}`,
      temple_recommend: 'Active', living_ordinance: 'Yes', patriarchal_blessing: 'needs-profile-api',
    });
    const s = statusByAbbr(m, needsCategories);
    expect(s['TR']).toBe('done');     // Active
    expect(s['EN']).toBe('done');     // endowed
    expect(s['PB']).toBe('issue');    // sentinel → data issue, never shown as a flat "No"
  });
});

describe('nextSteps (the not-yet-done applicable milestones — investigator detail)', () => {
  it('returns only the incomplete, applicable milestones (excludes done + N/A)', () => {
    const m = member({ sex: 'F', baptism_date: '1 Jan 2000', friends: 'Yes' }); // friends done
    const labels = new Set(nextSteps(m).map((ms) => ms.abbr));
    expect(labels.has('F')).toBe(false);   // done → excluded
    expect(labels.has('AP')).toBe(false);  // N/A for a woman → excluded
    expect(labels.has('C')).toBe(true);    // not done → included
  });

  it('is empty when every applicable milestone is complete', () => {
    const m = member({
      sex: 'F', baptism_date: '1 Jan 2000', friends: 'Yes', calling: 'Yes',
      ministering_brothers_sisters: 'Yes', ministering_assignment: 'Yes',
      family_name_prepared: 'Yes', first_temple_visit: 'Yes',
    });
    expect(nextSteps(m)).toHaveLength(0);
  });
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
    // F adult, 1yr member: applicable = Friends, Calling, Ministers-assigned, Ministering-assignment.
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

describe('unitGoldenHour (#8d per-unit indicators)', () => {
  const full = (unit: string) => member({
    unit_name: unit, sex: 'F', baptism_date: '1 Jan 2000', friends: 'Yes', calling: 'Yes',
    ministering_brothers_sisters: 'Yes', ministering_assignment: 'Yes',
    family_name_prepared: 'Yes', first_temple_visit: 'Yes',
  });
  it('groups by unit (people desc), counts fully-complete people + items done/total', () => {
    const out = unitGoldenHour([
      full('Alpha'),
      member({ unit_name: 'Alpha', sex: 'F', baptism_date: '1 Jan 2000' }), // nothing done
      full('Beta'),
    ]);
    expect(out.map((u) => u.unit)).toEqual(['Alpha', 'Beta']); // Alpha has 2 people → first
    const alpha = out.find((u) => u.unit === 'Alpha')!;
    expect(alpha.people).toBe(2);
    expect(alpha.fullyComplete).toBe(1); // only the full member
    expect(alpha.itemsDone).toBeGreaterThan(0);
    expect(alpha.itemsDone).toBeLessThan(alpha.itemsTotal); // the empty member drags items down
    const beta = out.find((u) => u.unit === 'Beta')!;
    expect(beta.fullyComplete).toBe(1);
    expect(beta.itemsDone).toBe(beta.itemsTotal); // its only member is fully complete
  });
});
