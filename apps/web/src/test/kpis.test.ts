// Tests for the KPI math ported from dashboard_common.dart: baptisms-by-month (#1/#2), metric
// bucketing (unique people per period), and the lesson/completion helpers.

import { describe, it, expect } from 'vitest';
import {
  baptismsByMonth, metricData, attendedDates, lessonsWithMember, membersWithMemberLessons,
  sacramentWindow,
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
    // A female adult born 1990 is eligible for 6 milestones (Friends, Has ministers, Calling ≥12,
    // Ministering assignment ≥14, Family name ≥12, First temple visit ≥12 — none of these is
    // sex-gated). Only Friends is done → 1/6.
    const m: Member = { sex: 'F', birth_date: '1 Jan 1990', friends: 'Yes', ministering_brothers_sisters: 'No' };
    expect(avgCompletion([m])).toBeCloseTo(1 / 6, 5);
  });
});

describe('sacramentWindow (last-8-weeks attendance, not whole-history "missed")', () => {
  function weeksAgo(n: number): string {
    const d = new Date();
    d.setDate(d.getDate() - n * 7);
    return iso(d);
  }

  it('returns null when there is no attendance list', () => {
    expect(sacramentWindow(undefined)).toBeNull();
    expect(sacramentWindow([])).toBeNull();
  });

  it('caps the window at 8 weeks even with a long history (no "52 of 54")', () => {
    // 54 weekly records, attended exactly 2 of the most recent 8.
    const list = Array.from({ length: 54 }, (_, i) => ({
      date: weeksAgo(i),
      attended: i === 1 || i === 4, // two of the recent 8 attended
    }));
    expect(sacramentWindow(list)).toEqual({ attended: 2, total: 8 });
  });

  it('uses fewer weeks when there is less data (started 2 weeks ago → out of 2)', () => {
    const list = [
      { date: weeksAgo(0), attended: true },
      { date: weeksAgo(1), attended: false },
    ];
    expect(sacramentWindow(list)).toEqual({ attended: 1, total: 2 });
  });

  it('sorts newest-first by date regardless of stored order', () => {
    const list = [
      { date: weeksAgo(10), attended: false }, // outside the window
      { date: weeksAgo(0), attended: true },
      { date: weeksAgo(1), attended: true },
    ];
    // window = the 2 most recent (both attended); the 10-weeks-ago miss is excluded.
    expect(sacramentWindow(list, 2)).toEqual({ attended: 2, total: 2 });
  });

  it('falls back to stored order when entries have no dates', () => {
    const list = [
      { attended: true },
      { attended: false },
      { attended: true },
    ];
    expect(sacramentWindow(list)).toEqual({ attended: 2, total: 3 });
  });
});
