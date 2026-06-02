// Mirrors apps/viewer/test/dashboard_dates_test.dart — date parsing across LCR's formats is the
// part most likely to silently misbehave, so the same cases are pinned here.

import { describe, it, expect } from 'vitest';
import { parseMemberDate, fmtLong, monthsDaysAgo } from '../logic/dates';

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
