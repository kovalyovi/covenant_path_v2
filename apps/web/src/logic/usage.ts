// Usage rollups for the ops console — "how often is this actually used, by unit and by calling?".
//
// The server (migration 0066, usage_summary/usage_daily) already does the aggregation and hands back
// nothing but counts: no email, no name, no person id. This module only shapes those rows for
// display, so it stays pure and unit-tested like logic/kpis.ts and logic/fieldGaps.ts.
//
// The counted unit is a PERSON-DAY: one row per person per surface per day they opened the app. So
// `events` answers "how many days of use" and `people` answers "by how many different people" — the
// two numbers a leader-adoption question actually needs, and neither can be inflated by someone
// leaving a tab open.

export type UsageDimension = 'unit' | 'calling' | 'surface';

/** One aggregate row exactly as usage_summary() returns it. */
export interface UsageSummaryRow {
  dimension: string;
  label: string;
  events: number;
  people: number;
  last_used: string | null;
}

/** One row of usage_daily(). */
export interface UsageDailyRow {
  day: string;
  events: number;
  people: number;
}

export interface UsageBar {
  label: string;
  events: number;
  people: number;
  lastUsed: string | null;
  /** 0..1 of the busiest row in the same dimension — drives the bar width. */
  share: number;
}

function num(v: unknown): number {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
}

/** Normalize whatever PostgREST hands back (numbers arrive as numbers, bigints can arrive as
 *  strings) into typed rows. Unknown dimensions are kept — a future dimension shouldn't vanish. */
export function parseUsageRows(raw: unknown): UsageSummaryRow[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((r) => {
    const o = (r ?? {}) as Record<string, unknown>;
    return {
      dimension: String(o['dimension'] ?? ''),
      label: String(o['label'] ?? ''),
      events: num(o['events']),
      people: num(o['people']),
      last_used: o['last_used'] == null ? null : String(o['last_used']),
    };
  });
}

/** The rows for one dimension, busiest first, with a share of the top row for the bars. */
export function usageBars(rows: UsageSummaryRow[], dimension: UsageDimension): UsageBar[] {
  const mine = rows.filter((r) => r.dimension === dimension);
  const top = Math.max(1, ...mine.map((r) => r.events));
  return mine
    .slice()
    .sort((a, b) => b.events - a.events || b.people - a.people || a.label.localeCompare(b.label))
    .map((r) => ({
      label: r.label,
      events: r.events,
      people: r.people,
      lastUsed: r.last_used,
      share: r.events / top,
    }));
}

/** Headline numbers. `people` is a MAX across dimensions, never a sum: the same person appears once
 *  per dimension, so adding them would double-count. Every dimension partitions the same rows, so
 *  the largest per-dimension distinct count is the true total. */
export function usageTotals(rows: UsageSummaryRow[]): {
  events: number;
  people: number;
  units: number;
  callings: number;
} {
  const byDim = (d: UsageDimension) => rows.filter((r) => r.dimension === d);
  const units = byDim('unit');
  const callings = byDim('calling');
  const surfaces = byDim('surface');
  return {
    // Same reasoning for events: sum ONE dimension, not all of them.
    events: units.reduce((a, r) => a + r.events, 0),
    people: Math.max(0, ...[units, callings, surfaces].map((g) => Math.max(0, ...g.map((r) => r.people)))),
    units: units.length,
    callings: callings.length,
  };
}

/** Daily person-day counts padded to a contiguous `days`-long series ending today, so the sparkline
 *  shows quiet days as gaps rather than silently compressing them away. */
export function usageSeries(rows: UsageDailyRow[], days: number, today = new Date()): number[] {
  const by = new Map<string, number>();
  for (const r of rows) by.set(String(r.day).slice(0, 10), num(r.events));
  const out: number[] = [];
  // Step through UTC dates: usage_daily buckets by UTC day, so building the axis in UTC keeps the
  // last bucket aligned with "today" for an admin in any timezone.
  const end = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  for (let i = days - 1; i >= 0; i -= 1) {
    const d = new Date(end - i * 86400000);
    out.push(by.get(d.toISOString().slice(0, 10)) ?? 0);
  }
  return out;
}
