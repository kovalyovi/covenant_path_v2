// Usage rollups (ops console). The counted unit is a PERSON-DAY, and the two traps these pin are
// (a) summing `people` across dimensions, which double-counts everyone once per dimension, and
// (b) letting a quiet day vanish from the trend instead of showing as a zero.

import { describe, it, expect } from 'vitest';
import {
  parseUsageRows,
  usageBars,
  usageTotals,
  usageSeries,
  type UsageSummaryRow,
} from '../logic/usage';

const rows: UsageSummaryRow[] = [
  { dimension: 'unit', label: 'Bond Park Ward', events: 12, people: 3, last_used: '2026-08-31' },
  { dimension: 'unit', label: 'Green Level Ward', events: 4, people: 2, last_used: '2026-08-29' },
  { dimension: 'calling', label: 'Bishop', events: 10, people: 2, last_used: '2026-08-31' },
  { dimension: 'calling', label: 'Relief Society President', events: 6, people: 3, last_used: '2026-08-30' },
  { dimension: 'surface', label: 'web', events: 14, people: 4, last_used: '2026-08-31' },
  { dimension: 'surface', label: 'ios', events: 2, people: 1, last_used: '2026-08-28' },
];

describe('parseUsageRows', () => {
  it('coerces PostgREST bigint-as-string counts to numbers', () => {
    const out = parseUsageRows([
      { dimension: 'unit', label: 'A', events: '7', people: '2', last_used: '2026-08-31' },
    ]);
    expect(out[0].events).toBe(7);
    expect(out[0].people).toBe(2);
  });

  it('is empty for a non-array (an RPC that errored out)', () => {
    expect(parseUsageRows(null)).toEqual([]);
    expect(parseUsageRows({ message: 'nope' })).toEqual([]);
  });

  it('keeps a null last_used rather than inventing a date', () => {
    expect(parseUsageRows([{ dimension: 'unit', label: 'A' }])[0].last_used).toBeNull();
  });
});

describe('usageBars', () => {
  it('returns only the asked-for dimension, busiest first', () => {
    expect(usageBars(rows, 'calling').map((b) => b.label)).toEqual([
      'Bishop',
      'Relief Society President',
    ]);
  });

  it('scales share against the busiest row of that dimension', () => {
    const bars = usageBars(rows, 'unit');
    expect(bars[0].share).toBe(1);
    expect(bars[1].share).toBeCloseTo(4 / 12);
  });

  it('never divides by zero when every row is empty', () => {
    const bars = usageBars([{ dimension: 'unit', label: 'A', events: 0, people: 0, last_used: null }], 'unit');
    expect(bars[0].share).toBe(0);
  });

  it('is empty for a dimension with no rows', () => {
    expect(usageBars(rows, 'unit' as never).length).toBeGreaterThan(0);
    expect(usageBars([], 'calling')).toEqual([]);
  });
});

describe('usageTotals', () => {
  it('counts people ONCE, not once per dimension', () => {
    // 4 distinct people show up in all three dimensions; summing would claim 4+5+5 = 14.
    expect(usageTotals(rows).people).toBe(4);
  });

  it('counts person-days from a single dimension, not across all of them', () => {
    expect(usageTotals(rows).events).toBe(16); // 12 + 4, not 16 + 16 + 16
  });

  it('reports how many units and callings appear', () => {
    const t = usageTotals(rows);
    expect(t.units).toBe(2);
    expect(t.callings).toBe(2);
  });

  it('is all zeroes with no data', () => {
    expect(usageTotals([])).toEqual({ events: 0, people: 0, units: 0, callings: 0 });
  });
});

describe('usageSeries', () => {
  const today = new Date('2026-08-31T12:00:00Z');

  it('pads quiet days with zeroes and ends on today', () => {
    const s = usageSeries(
      [{ day: '2026-08-31', events: 5, people: 2 }, { day: '2026-08-29', events: 1, people: 1 }],
      4,
      today,
    );
    expect(s).toEqual([0, 1, 0, 5]);
  });

  it('ignores days outside the window', () => {
    const s = usageSeries([{ day: '2026-01-01', events: 99, people: 9 }], 3, today);
    expect(s).toEqual([0, 0, 0]);
  });

  it('tolerates a full timestamp in the day column', () => {
    const s = usageSeries([{ day: '2026-08-31T00:00:00+00:00', events: 2, people: 1 }], 2, today);
    expect(s).toEqual([0, 2]);
  });
});
