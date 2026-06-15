// Pins the Table tab's filter contract: every ENUMERABLE (small, categorical) tracked covenant-path
// column gets a per-value filter, while genuinely continuous/free-form columns stay sort-only.
//
// Regression guard for the missing-sex-filter fix (2026-06-14): `sex` is a tiny M/F enum like the
// status columns, so "show only sisters/brothers" must be filterable. It was previously lumped in
// with the continuous columns and had no filter. The native iOS/Android tables already filter every
// column; this brings web into parity for the enumerable fields.

import { describe, it, expect, vi } from 'vitest';

// Importing TableTab transitively pulls in useDashboard → lib/supabase, which calls createClient at
// module-eval time and throws without VITE_SUPABASE_* env. We only need the static COLS/FILTERABLE
// contract, so stub the supabase + dashboard modules (same pattern as sync_settings.test.tsx).
vi.mock('../lib/supabase', () => ({ supabase: {}, currentAccessToken: async () => 'token' }));
vi.mock('../hooks/useDashboard', () => ({ useDashboard: () => ({}) }));

import { COLS, FILTERABLE } from '../pages/tabs/TableTab';

// The columns whose values are genuinely continuous / free-form — a per-value checkbox filter there
// is just noise, so they intentionally SORT only and must NOT be in FILTERABLE.
const SORT_ONLY = new Set([
  'name',                 // free text
  'age',                  // continuous (years)
  'baptism_date',         // a date
  'membership_duration',  // derived from the baptism date (tenure ordering)
  'friends',              // a count
]);

describe('Table filter contract', () => {
  it('makes every enumerable tracked column filterable (and only those)', () => {
    for (const col of COLS) {
      const filterable = FILTERABLE.has(col.key);
      if (SORT_ONLY.has(col.key)) {
        expect(filterable, `${col.key} is continuous/free-form → sort-only`).toBe(false);
      } else {
        expect(filterable, `${col.key} is enumerable → must be filterable`).toBe(true);
      }
    }
  });

  it('lets a leader filter by sex (M/F) — the fix', () => {
    expect(COLS.some((c) => c.key === 'sex')).toBe(true);
    expect(FILTERABLE.has('sex')).toBe(true);
  });

  it('keeps continuous columns (age, baptism, member-for, friends, name) sort-only', () => {
    for (const k of SORT_ONLY) expect(FILTERABLE.has(k)).toBe(false);
  });

  it('every FILTERABLE key is an actual column key', () => {
    const keys = new Set(COLS.map((c) => c.key));
    for (const k of FILTERABLE) expect(keys.has(k)).toBe(true);
  });
});
