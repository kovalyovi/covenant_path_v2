// Tests for the KPI math ported from dashboard_common.dart: baptisms-by-month (#1/#2), metric
// bucketing (unique people per period), and the lesson/completion helpers.

import { describe, it, expect } from 'vitest';
import {
  baptismsByMonth, metricData, attendedDates, lessonsWithMember, membersWithMemberLessons,
} from '../logic/kpis';
import { avgCompletion } from '../logic/milestones';
import type { Member } from '../lib/member';

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

describe('baptismsByMonth (#1/#2)', () => {
  it('counts each convert once, in their baptism month, and names the best month', () => {
    const now = new Date();
    // Use the 1st of past months so nothing is future-dated (a day-of-month near today could be).
    const monthsAgo = (n: number) => new Date(now.getFullYear(), now.getMonth() - n, 1);
    const oneMonthAgo = monthsAgo(1);
    const twoMonthsAgo = monthsAgo(2);
    const rows: Member[] = [
      { person_uuid: 'a', baptism_date: iso(oneMonthAgo) },
      { person_uuid: 'b', baptism_date: iso(oneMonthAgo) },
      { person_uuid: 'c', baptism_date: iso(twoMonthsAgo) },
    ];
    const r = baptismsByMonth(rows, 'm12');
    expect(r.total).toBe(3);
    expect(r.bestCount).toBe(2); // one-month-ago has 2
    expect(r.events).toHaveLength(3);
    // the busiest bucket (one month ago) holds 2
    expect(Math.max(...r.counts)).toBe(2);
  });

  it('skips rows without a real baptism date and future-dated baptisms', () => {
    const future = new Date();
    future.setFullYear(future.getFullYear() + 1);
    const rows: Member[] = [
      { person_uuid: 'x', baptism_date: 'N/A' },
      { person_uuid: 'y', baptism_date: iso(future) },
    ];
    const r = baptismsByMonth(rows, 'all');
    expect(r.total).toBe(0);
  });

  it('YTD window starts at Jan of the current year', () => {
    const now = new Date();
    const r = baptismsByMonth([], 'ytd');
    // Jan..current month inclusive
    expect(r.labels.length).toBe(now.getMonth() + 1);
  });
});

describe('metricData (sacrament attendance bucketing)', () => {
  it('counts a member once per period even if they attended multiple Sundays', () => {
    const now = new Date();
    const a = new Date(now.getFullYear(), now.getMonth(), 2);
    const b = new Date(now.getFullYear(), now.getMonth(), 9);
    const rows: Member[] = [
      {
        person_uuid: 'm1',
        details: {
          sacrament: [
            { date: iso(a), attended: true },
            { date: iso(b), attended: true },
          ],
        },
      },
    ];
    const r = metricData(rows, attendedDates, 'year');
    // both Sundays fall in the same (current) month bucket → counted once
    const total = r.series.current.reduce((acc, n) => acc + n, 0);
    expect(total).toBe(1);
  });

  it('ignores non-attended entries', () => {
    const now = new Date();
    const rows: Member[] = [
      {
        person_uuid: 'm2',
        details: { sacrament: [{ date: iso(new Date(now.getFullYear(), now.getMonth(), 5)), attended: false }] },
      },
    ];
    const r = metricData(rows, attendedDates, 'year');
    expect(r.series.current.reduce((a, n) => a + n, 0)).toBe(0);
  });
});

describe('lessons + completion helpers', () => {
  const rows: Member[] = [
    {
      person_uuid: 'p1',
      details: {
        lessons: [
          { principles: [{ memberPresent: true }, { memberPresent: false }] },
          { principles: [{ memberPresent: false }] },
        ],
      },
    },
    { person_uuid: 'p2', details: { lessons: [{ principles: [{ memberPresent: true }] }] } },
    { person_uuid: 'p3', details: { lessons: [] } },
  ];

  it('lessonsWithMember counts lessons with ≥1 member-present principle', () => {
    expect(lessonsWithMember(rows)).toBe(2); // p1 lesson 1 + p2 lesson 1
  });

  it('membersWithMemberLessons ranks members by member-present lesson count', () => {
    const ranked = membersWithMemberLessons(rows);
    expect(ranked.map((r) => r.m['person_uuid'])).toEqual(['p1', 'p2']);
    expect(ranked[0].count).toBe(1);
  });

  it('avgCompletion is eligible-only and 0 for empty input', () => {
    expect(avgCompletion([])).toBe(0);
    // A female adult born 1990 is eligible for 4 milestones (Friends, Has ministers, Calling ≥12,
    // Ministering assignment ≥14 — neither calling nor giving-ministering is sex-gated). Only
    // Friends is done → 1/4 = 0.25.
    const m: Member = { sex: 'F', birth_date: '1 Jan 1990', friends: 'Yes', ministering_brothers_sisters: 'No' };
    expect(avgCompletion([m])).toBeCloseTo(0.25, 5);
  });
});
