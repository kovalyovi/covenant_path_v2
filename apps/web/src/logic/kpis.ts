// KPI math ported from apps/viewer/lib/views/dashboard_common.dart. These are the stat engines
// behind the KPIs tab: baptisms-by-month (#1/#2), the metric line-chart series (sacrament /
// first-lesson), lessons-with-member, and per-unit completion. Kept framework-free so they're
// unit-testable in isolation (mirroring the Flutter tests).

import type { Member } from '../lib/member';
import { detailsOf, memberId } from '../lib/member';
import {
  parseMemberDate, weekStart, fmtMonthDay, fmtMonShort, fmtFullMonYear,
} from './dates';

// ---- Baptisms by month (#1/#2) -----------------------------------------------------------------

export type BWindow = 'ytd' | 'm12' | 'm24' | 'all';

/** One matching person counted toward a metric on a date, mapped to a chart bucket index. */
export interface Ev {
  m: Member;
  date: Date;
  bucket: number;
}

export interface BaptismsByMonth {
  labels: string[];
  counts: number[];
  events: Ev[];
  bestLabel: string | null;
  bestCount: number;
  total: number;
}

/**
 * Baptized converts counted by their **baptism month** over [window]. Returns ordered monthly
 * labels + counts (for the chart), per-baptism events (for the by-unit drill), the in-window total,
 * and the BEST month (most baptisms), named. Mirrors `_baptismsByMonth`.
 */
export function baptismsByMonth(baptized: Iterable<Member>, window: BWindow): BaptismsByMonth {
  const today = new Date();
  let start: Date | null;
  switch (window) {
    case 'ytd': start = new Date(today.getFullYear(), 0, 1); break;
    case 'm12': start = new Date(today.getFullYear(), today.getMonth() - 11, 1); break;
    case 'm24': start = new Date(today.getFullYear(), today.getMonth() - 23, 1); break;
    case 'all': start = null; break;
  }

  const pairs: Array<[Member, Date]> = [];
  for (const m of baptized) {
    const dt = parseMemberDate(m['baptism_date']);
    if (dt == null || dt.getTime() > today.getTime()) continue; // no real / future date → skip
    if (start != null && dt.getTime() < start.getTime()) continue;
    pairs.push([m, dt]);
  }

  let rangeStart: Date;
  if (start != null) {
    rangeStart = start;
  } else if (pairs.length === 0) {
    rangeStart = new Date(today.getFullYear(), today.getMonth(), 1);
  } else {
    const e = pairs.reduce((a, b) => (a[1].getTime() < b[1].getTime() ? a : b))[1];
    rangeStart = new Date(e.getFullYear(), e.getMonth(), 1);
  }

  const labels: string[] = [];
  const keys: number[] = [];
  let y = rangeStart.getFullYear();
  let mo = rangeStart.getMonth() + 1; // 1-based to match Dart's month*100 keys
  while (y < today.getFullYear() || (y === today.getFullYear() && mo <= today.getMonth() + 1)) {
    keys.push(y * 100 + mo);
    const d = new Date(y, mo - 1);
    labels.push(y === today.getFullYear() ? fmtMonShort(d) : `${fmtMonShort(d)} '${String(y).slice(2)}`);
    if (++mo > 12) { mo = 1; y++; }
  }

  const idxOf = new Map<number, number>();
  keys.forEach((k, i) => idxOf.set(k, i));
  const counts = new Array<number>(keys.length).fill(0);
  const events: Ev[] = [];
  for (const [m, dt] of pairs) {
    const i = idxOf.get(dt.getFullYear() * 100 + dt.getMonth() + 1);
    if (i == null) continue;
    counts[i] += 1;
    events.push({ m, date: dt, bucket: i });
  }

  let bi = -1;
  let bc = 0;
  for (let i = 0; i < counts.length; i++) {
    if (counts[i] > bc) { bc = counts[i]; bi = i; }
  }
  return {
    labels,
    counts,
    events,
    bestLabel: bi >= 0 ? fmtFullMonYear(new Date(Math.floor(keys[bi] / 100), (keys[bi] % 100) - 1)) : null,
    bestCount: bc,
    total: counts.reduce((a, b) => a + b, 0),
  };
}

// ---- Metric line series (week/month buckets vs. previous window) -------------------------------

export type Period = 'month' | 'ytd' | 'year' | 'all' | 'custom';

/** #7: an inclusive custom date range for the 'custom' period. */
export interface DateRange {
  start: Date;
  end: Date;
}

export interface Series {
  labels: string[];
  current: number[];
  prev: number[];
}

export interface MetricData {
  series: Series;
  events: Ev[];
}

function bucketKey(dt: Date, p: Period, allByYear: boolean): number {
  switch (p) {
    case 'month': {
      const w = weekStart(dt);
      return w.getFullYear() * 10000 + (w.getMonth() + 1) * 100 + w.getDate();
    }
    case 'ytd':
    case 'year':
    case 'custom':
      return dt.getFullYear() * 100 + dt.getMonth() + 1;
    case 'all':
      return allByYear ? dt.getFullYear() : dt.getFullYear() * 100 + dt.getMonth() + 1;
  }
}

function windowBuckets(p: Period, today: Date, shift: number, custom?: DateRange): Array<[number, string]> {
  switch (p) {
    case 'month': {
      const end = weekStart(today);
      end.setDate(end.getDate() - shift * 5 * 7);
      const out: Array<[number, string]> = [];
      for (let i = 4; i >= 0; i--) {
        const w = new Date(end);
        w.setDate(w.getDate() - i * 7);
        out.push([w.getFullYear() * 10000 + (w.getMonth() + 1) * 100 + w.getDate(), fmtMonthDay(w)]);
      }
      return out;
    }
    case 'year': {
      const out: Array<[number, string]> = [];
      for (let i = 11; i >= 0; i--) {
        const m = new Date(today.getFullYear(), today.getMonth() - shift * 12 - i, 1);
        out.push([m.getFullYear() * 100 + m.getMonth() + 1, fmtMonShort(m)]);
      }
      return out;
    }
    case 'ytd': {
      // Calendar year-to-date: Jan..current month of (this year − shift). shift=1 → last year's same
      // Jan..now span, position-aligned, so "Compare to previous" is a year-over-year overlay.
      const y = today.getFullYear() - shift;
      const out: Array<[number, string]> = [];
      for (let mo = 1; mo <= today.getMonth() + 1; mo++) out.push([y * 100 + mo, fmtMonShort(new Date(y, mo - 1))]);
      return out;
    }
    case 'custom': {
      // #7: monthly buckets from start..end, shifted back `shift` YEARS so the compare overlay is the
      // same calendar range one year earlier (year-over-year).
      if (!custom) return [];
      const out: Array<[number, string]> = [];
      let y = custom.start.getFullYear() - shift;
      let mo = custom.start.getMonth() + 1;
      const endY = custom.end.getFullYear() - shift;
      const endMo = custom.end.getMonth() + 1;
      while (y < endY || (y === endY && mo <= endMo)) {
        const d = new Date(y, mo - 1);
        out.push([y * 100 + mo, y === today.getFullYear() ? fmtMonShort(d) : `${fmtMonShort(d)} '${String(y).slice(2)}`]);
        if (++mo > 12) { mo = 1; y++; }
      }
      return out;
    }
    case 'all':
      return [];
  }
}

/**
 * Series for the chart (unique people per bucket, recent window vs. preceding one) PLUS the
 * underlying events so a tap can show who. Mirrors `_metricData`.
 */
export function metricData(
  rows: Iterable<Member>,
  datesOf: (m: Member) => Date[],
  period: Period,
  customRange?: DateRange,
): MetricData {
  const today = new Date();
  const pairs: Array<[Member, Date]> = [];
  for (const m of rows) {
    for (const dt of datesOf(m)) pairs.push([m, dt]);
  }

  let allByYear = false;
  if (period === 'all' && pairs.length > 0) {
    const earliest = pairs.reduce((a, b) => (a[1].getTime() < b[1].getTime() ? a : b))[1];
    const months = (today.getFullYear() - earliest.getFullYear()) * 12 + (today.getMonth() - earliest.getMonth());
    allByYear = months > 36;
  }

  const sets = new Map<number, Set<string>>();
  const raw: Array<[Member, Date, number]> = [];
  for (const [m, dt] of pairs) {
    const id = memberId(m);
    const key = bucketKey(dt, period, allByYear);
    if (!sets.has(key)) sets.set(key, new Set());
    sets.get(key)!.add(id);
    raw.push([m, dt, key]);
  }

  let cur: Array<[number, string]>;
  let prev: Array<[number, string]>;
  if (period === 'all') {
    if (raw.length === 0) return { series: { labels: [], current: [], prev: [] }, events: [] };
    const earliest = raw.reduce((a, b) => (a[1].getTime() < b[1].getTime() ? a : b))[1];
    cur = [];
    if (allByYear) {
      for (let y = earliest.getFullYear(); y <= today.getFullYear(); y++) cur.push([y, String(y)]);
    } else {
      let y = earliest.getFullYear();
      let mo = earliest.getMonth() + 1;
      while (y < today.getFullYear() || (y === today.getFullYear() && mo <= today.getMonth() + 1)) {
        const d = new Date(y, mo - 1);
        const lbl = y === today.getFullYear() ? fmtMonShort(d) : `${fmtMonShort(d)} '${String(y).slice(2)}`;
        cur.push([y * 100 + mo, lbl]);
        if (++mo > 12) { mo = 1; y++; }
      }
    }
    prev = [];
  } else {
    cur = windowBuckets(period, today, 0, customRange);
    prev = windowBuckets(period, today, 1, customRange);
  }

  const idxOf = new Map<number, number>();
  cur.forEach(([k], i) => idxOf.set(k, i));
  const series: Series = {
    labels: cur.map(([, l]) => l),
    current: cur.map(([k]) => sets.get(k)?.size ?? 0),
    prev: prev.map(([k]) => sets.get(k)?.size ?? 0),
  };
  const events: Ev[] = [];
  for (const [m, dt, key] of raw) {
    const i = idxOf.get(key);
    if (i != null) events.push({ m, date: dt, bucket: i });
  }
  return { series, events };
}

/** Recent sacrament attendance over the last 8 weeks of available data. We never show "52 missed of
 *  54" (the whole history): a leader cares about the RECENT trend. The window is the most recent up-to-8
 *  weekly records — fewer when there's less data (a member who started 2 weeks ago shows out of 2).
 *  `attended` is how many of those `total` weeks they were present.
 *
 *  Robust to either array order (LCR/Member Tools store oldest- or newest-first): each entry is one
 *  weekly sacrament meeting, so we sort by date desc when dates are present, else trust the stored
 *  order, then take the first `weeks` (default 8). Entries without an `attended:true` flag count as
 *  missed (the same rule the dots use). Returns null when there's no attendance list at all. */
export const SACRAMENT_WINDOW_WEEKS = 8;

export function sacramentWindow(
  list: Array<Record<string, unknown>> | undefined | null,
  weeks: number = SACRAMENT_WINDOW_WEEKS,
): { attended: number; total: number } | null {
  if (!Array.isArray(list) || list.length === 0) return null;
  const withDates = list.map((s) => ({ s, dt: parseMemberDate(s?.['date']) }));
  const anyDates = withDates.some((x) => x.dt != null);
  const ordered = anyDates
    // newest first; undated rows sink to the end so dated recents win the window
    ? [...withDates].sort((a, b) => (b.dt?.getTime() ?? -Infinity) - (a.dt?.getTime() ?? -Infinity))
    : withDates;
  const win = ordered.slice(0, Math.max(1, weeks));
  const attended = win.filter((x) => x.s?.['attended'] === true).length;
  return { attended, total: win.length };
}

/** Sundays this person was marked present at sacrament. Mirrors `_attendedDates`. */
export function attendedDates(m: Member): Date[] {
  const d = detailsOf(m);
  const sac = d?.['sacrament'];
  if (!Array.isArray(sac)) return [];
  const out: Date[] = [];
  for (const s of sac) {
    if (!s || typeof s !== 'object' || (s as Record<string, unknown>)['attended'] !== true) continue;
    const dt = parseMemberDate((s as Record<string, unknown>)['date']);
    if (dt != null) out.push(dt);
  }
  return out;
}

/** The single date this person started being taught (missionary "first lesson"). Mirrors `_firstLessonDate`. */
export function firstLessonDate(m: Member): Date[] {
  const fl = parseMemberDate(detailsOf(m)?.['firstLesson']);
  return fl != null ? [fl] : [];
}

/** Count of lessons taught (across people) where a member was present for ≥1 principle. Mirrors `_lessonsWithMember`. */
export function lessonsWithMember(rows: Member[]): number {
  let c = 0;
  for (const m of rows) {
    const lessons = detailsOf(m)?.['lessons'];
    if (!Array.isArray(lessons)) continue;
    for (const l of lessons) {
      if (!l || typeof l !== 'object') continue;
      const ps = (l as Record<string, unknown>)['principles'];
      if (Array.isArray(ps) && ps.some((p) => p && typeof p === 'object' && (p as Record<string, unknown>)['memberPresent'] === true)) {
        c++;
      }
    }
  }
  return c;
}

export interface MemberLessonCount {
  m: Member;
  count: number;
}

/** Members with ≥1 member-present lesson, ranked by count. Mirrors `_membersWithMemberLessons`. */
export function membersWithMemberLessons(rows: Member[]): MemberLessonCount[] {
  const out: MemberLessonCount[] = [];
  for (const m of rows) {
    const lessons = detailsOf(m)?.['lessons'];
    if (!Array.isArray(lessons)) continue;
    let c = 0;
    for (const l of lessons) {
      if (!l || typeof l !== 'object') continue;
      const ps = (l as Record<string, unknown>)['principles'];
      if (Array.isArray(ps) && ps.some((p) => p && typeof p === 'object' && (p as Record<string, unknown>)['memberPresent'] === true)) {
        c++;
      }
    }
    if (c > 0) out.push({ m, count: c });
  }
  out.sort((a, b) => b.count - a.count);
  return out;
}

export interface UnitCompletion {
  unit: string;
  pct: number;
  n: number;
}

/** Average Golden Hour completion per unit, ranked high→low. Mirrors `_unitCompletion`. */
export function unitCompletion(baptized: Member[], avg: (rows: Member[]) => number): UnitCompletion[] {
  const byUnit = new Map<string, Member[]>();
  for (const m of baptized) {
    const u = String(m['unit_name'] ?? '—');
    if (!byUnit.has(u)) byUnit.set(u, []);
    byUnit.get(u)!.push(m);
  }
  const out: UnitCompletion[] = [];
  for (const [unit, members] of byUnit) out.push({ unit, pct: avg(members), n: members.length });
  out.sort((a, b) => b.pct - a.pct);
  return out;
}

/** A fixed, calm 16-hue palette for per-unit accents (distinct from status/org/nav). Mirrors `_unitPalette`. */
export const UNIT_PALETTE = [
  '#00695C', '#4527A0', '#AD1457', '#283593',
  '#558B2F', '#6D4C41', '#00838F', '#C62828',
  '#EF6C00', '#1565C0', '#8E24AA', '#2E7D32',
  '#827717', '#006064', '#BF360C', '#37474F',
];

/** Each distinct unit → a palette color by SORTED INDEX (stable across categories). Mirrors `_assignUnitColors`. */
export function assignUnitColors(rows: Member[]): Map<string, string> {
  const units = [...new Set(rows.map((m) => String(m['unit_name'] ?? '—')))].sort();
  const map = new Map<string, string>();
  units.forEach((u, i) => map.set(u, UNIT_PALETTE[i % UNIT_PALETTE.length]));
  return map;
}
