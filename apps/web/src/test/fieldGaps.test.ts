import { describe, it, expect } from 'vitest';
import { fieldGapSeries } from '../logic/fieldGaps';

// The ops-dash "Field gaps (per day)" aggregation (track-missing-fields). Each sync run stamps a
// structured field-gap report into its diagnostics payload (run_stats.field_gaps); this rolls them up
// per day across stakes so a leader's "ministering is blank" shows as a number you can watch fall.
type Json = Record<string, unknown>;

function syncRun(run_at: string, stake_id: string, gaps: Record<string, { missing: number; reason?: string }>): Json {
  return {
    kind: 'sync',
    run_at,
    stake_id,
    payload: { run_stats: { field_gaps: { fields: gaps } } },
  };
}

describe('fieldGapSeries', () => {
  it('groups by day and sums members-missing per field across stakes', () => {
    const runs: Json[] = [
      syncRun('2026-06-15T08:00:00Z', 'A', { ministering_assignment: { missing: 12, reason: 're-auth' } }),
      syncRun('2026-06-15T08:05:00Z', 'B', { ministering_assignment: { missing: 18 } }),
      syncRun('2026-06-14T08:00:00Z', 'A', { ministering_assignment: { missing: 20 } }),
    ];
    const { days, fields, totals, reasons } = fieldGapSeries(runs);
    expect(days).toEqual(['2026-06-14', '2026-06-15']); // ascending (oldest → newest)
    expect(fields).toContain('ministering_assignment');
    // 2026-06-14: 20 (stake A only); 2026-06-15: 12 + 18 = 30 (A+B)
    expect(totals['ministering_assignment']).toEqual([20, 30]);
    expect(reasons['ministering_assignment']).toBe('re-auth');
  });

  it('keeps only the LATEST run per stake per day (re-runs do not double-count)', () => {
    const runs: Json[] = [
      // newest-first ordering, as the broker returns them
      syncRun('2026-06-15T12:00:00Z', 'A', { calling: { missing: 3 } }),
      syncRun('2026-06-15T06:00:00Z', 'A', { calling: { missing: 99 } }), // earlier same-day run — ignored
    ];
    const { totals } = fieldGapSeries(runs);
    expect(totals['calling']).toEqual([3]);
  });

  it('falls back to field_coverage (blocked + pending) for legacy runs without field_gaps', () => {
    const legacy: Json = {
      kind: 'sync',
      run_at: '2026-06-15T08:00:00Z',
      stake_id: 'A',
      payload: { field_coverage: { patriarchal_blessing: { filled: 50, blocked: 4, pending: 2 } } },
    };
    const { fields, totals } = fieldGapSeries([legacy]);
    expect(fields).toContain('patriarchal_blessing');
    expect(totals['patriarchal_blessing']).toEqual([6]); // 4 blocked + 2 pending
  });

  it('sorts fields by the most-recent day missing (worst first) and ignores non-sync rows', () => {
    const runs: Json[] = [
      syncRun('2026-06-15T08:00:00Z', 'A', { calling: { missing: 5 }, friends: { missing: 40 } }),
      { kind: 'probe', run_at: '2026-06-15T09:00:00Z', stake_id: 'A', payload: {} }, // not a sync — skipped
    ];
    const { fields } = fieldGapSeries(runs);
    expect(fields[0]).toBe('friends'); // 40 > 5
  });

  it('returns empty series when there is no telemetry', () => {
    expect(fieldGapSeries([]).days).toEqual([]);
    expect(fieldGapSeries([{ kind: 'probe', run_at: '2026-06-15', payload: {} }]).days).toEqual([]);
  });

  it('scopes to ONE stake when stakeId is passed (field gaps by stake)', () => {
    const runs: Json[] = [
      syncRun('2026-06-15T08:00:00Z', 'A', { patriarchal_blessing: { missing: 76 } }),
      syncRun('2026-06-15T08:05:00Z', 'B', { patriarchal_blessing: { missing: 27 }, calling: { missing: 4 } }),
      syncRun('2026-06-14T08:00:00Z', 'A', { patriarchal_blessing: { missing: 80 } }),
    ];
    const all = fieldGapSeries(runs);
    expect(all.totals['patriarchal_blessing']).toEqual([80, 103]); // A+B summed

    const onlyA = fieldGapSeries(runs, 10, 'A');
    expect(onlyA.totals['patriarchal_blessing']).toEqual([80, 76]); // A alone
    expect(onlyA.fields).not.toContain('calling'); // B-only gap excluded

    const onlyB = fieldGapSeries(runs, 10, 'B');
    expect(onlyB.days).toEqual(['2026-06-15']); // B has no 06-14 run
    expect(onlyB.totals['calling']).toEqual([4]);

    // '' / null = unscoped (the "All stakes" option)
    expect(fieldGapSeries(runs, 10, null).totals['patriarchal_blessing']).toEqual([80, 103]);
  });
});
