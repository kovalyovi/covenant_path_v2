// Mirrors apps/viewer/test/dashboard_dates_test.dart — date parsing across LCR's formats is the
// part most likely to silently misbehave, so the same cases are pinned here.

import { describe, it, expect } from 'vitest';
import {
  parseMemberDate, fmtLong, monthsDaysAgo, baptismElapsed, tenure, etHourToday, fmtEtHourLocal,
} from '../logic/dates';

describe('parseMemberDate', () => {
  it('parses "6 Feb 2026" and "06 Feb 2026"', () => {
    expect(parseMemberDate('6 Feb 2026')).toEqual(new Date(2026, 1, 6));
    expect(parseMemberDate('06 Feb 2026')).toEqual(new Date(2026, 1, 6));
  });

  it('parses ISO and MM/dd/yy', () => {
    expect(parseMemberDate('2026-02-06')).toEqual(new Date(2026, 1, 6));
    expect(parseMemberDate('02/06/26')).toEqual(new Date(2026, 1, 6));
  });

  it('parses full month names', () => {
    expect(parseMemberDate('6 February 2026')).toEqual(new Date(2026, 1, 6));
  });

  it('returns null for blanks and sentinels', () => {
    expect(parseMemberDate(null)).toBeNull();
    expect(parseMemberDate('')).toBeNull();
    expect(parseMemberDate('N/A')).toBeNull();
    expect(parseMemberDate('needs-profile-api')).toBeNull();
  });
});

describe('fmtLong', () => {
  it('is a full human-readable date', () => {
    expect(fmtLong(new Date(2026, 1, 6))).toBe('Friday, February 6, 2026');
    expect(fmtLong(null)).toBe('');
  });
});

describe('monthsDaysAgo', () => {
  it('null and future dates return empty', () => {
    expect(monthsDaysAgo(null)).toBe('');
    const future = new Date();
    future.setDate(future.getDate() + 10);
    expect(monthsDaysAgo(future)).toBe('');
  });

  it('recent dates read in days', () => {
    const d = new Date();
    d.setDate(d.getDate() - 3);
    const r = monthsDaysAgo(d);
    expect(r).toContain('day');
    expect(r).not.toContain('month');
  });

  it('older dates include months, with correct pluralization', () => {
    const d = new Date();
    d.setDate(d.getDate() - 75);
    expect(monthsDaysAgo(d)).toContain('month');
    // exactly today reads "0 days" (never empty/negative)
    expect(monthsDaysAgo(new Date())).toContain('day');
  });
});

describe('baptismElapsed', () => {
  it('drops the trailing days once there is at least one month', () => {
    const d = new Date();
    d.setMonth(d.getMonth() - 3);
    d.setDate(d.getDate() - 12); // 3 months + ~12 days
    const r = baptismElapsed(d);
    expect(r).toBe('3 months');
    expect(r).not.toContain('day');
  });

  it('shows days when under a month', () => {
    const d = new Date();
    d.setDate(d.getDate() - 5);
    expect(baptismElapsed(d)).toBe('5 days');
  });

  it('singular month keeps its label and still drops days', () => {
    const d = new Date();
    d.setMonth(d.getMonth() - 1);
    d.setDate(d.getDate() - 3);
    expect(baptismElapsed(d)).toBe('1 month');
  });

  it('null and future dates return empty', () => {
    expect(baptismElapsed(null)).toBe('');
    const future = new Date();
    future.setDate(future.getDate() + 10);
    expect(baptismElapsed(future)).toBe('');
  });
});

describe('tenure (#9e — "Member for")', () => {
  function ago(years: number, months: number, days = 0): Date {
    const d = new Date();
    d.setFullYear(d.getFullYear() - years, d.getMonth() - months, d.getDate() - days);
    return d;
  }
  it('drops zero parts: years+months, never "0 years"/"0 months"', () => {
    expect(tenure(ago(2, 3))).toBe('2 years 3 months');
    expect(tenure(ago(1, 0))).toBe('1 year');          // no "0 months"
    expect(tenure(ago(0, 5))).toBe('5 months');        // no "0 years"
    expect(tenure(ago(0, 2))).toBe('2 months');        // exactly 2 months: no days
  });
  it('shows days only under 2 months', () => {
    expect(tenure(ago(0, 1, 3))).toBe('1 month 3 days');
    expect(tenure(ago(0, 0, 5))).toBe('5 days');
  });
  it('null and future dates return empty', () => {
    expect(tenure(null)).toBe('');
    const f = new Date(); f.setDate(f.getDate() + 10);
    expect(tenure(f)).toBe('');
  });
});

// The sync schedule is STORED as an ET hour but DISPLAYED local. These invariants hold in
// whatever timezone the test runner uses: converting the returned instant back to
// America/New_York must land exactly on the requested wall-clock hour.
describe('etHourToday / fmtEtHourLocal', () => {
  const inET = (d: Date, opts: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', ...opts }).format(d);

  it('returns an instant whose ET wall clock is the requested hour, on the hour', () => {
    for (const h of [0, 7, 12, 23]) {
      const d = etHourToday(h);
      expect(Number(inET(d, { hour: 'numeric', hourCycle: 'h23' }))).toBe(h);
      expect(Number(inET(d, { minute: 'numeric' }))).toBe(0);
    }
  });

  it('formats that instant as the local wall-clock time (h:mm AM/PM)', () => {
    const s = fmtEtHourLocal(7);
    expect(s).toMatch(/^\d{1,2}:\d{2} (AM|PM)$/);
    const d = etHourToday(7);
    const h24 = d.getHours();
    const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
    expect(s).toBe(`${h12}:${String(d.getMinutes()).padStart(2, '0')} ${h24 < 12 ? 'AM' : 'PM'}`);
  });
});
