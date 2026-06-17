// Senior-missionary filtering on the per-person Baptisms card (2026-06-17). Senior couples (husband &
// wife serving together — a shared surname) are dropped from the baptism card, which shows the one
// TEACHING companionship; they remain visible in the "Missionaries by Unit" section. Names sync as
// "Surname, Given".

import { describe, expect, it, vi } from 'vitest';

// Importing Missionaries.tsx transitively pulls in useDashboard → lib/supabase, which calls
// createClient at module-eval time and throws without VITE_SUPABASE_* env. We only need the pure
// helpers, so stub those modules (same pattern as tableFilters.test.ts / sync_settings.test.tsx).
vi.mock('../lib/supabase', () => ({ supabase: {}, currentAccessToken: async () => 'token' }));
vi.mock('../hooks/useDashboard', () => ({ useDashboard: () => ({}) }));

import { isSeniorCouple, baptismCardMissionaries } from '../components/Missionaries';
import type { Companionship } from '../components/Missionaries';

const comp = (...names: string[]): Companionship => ({ missionaries: names.map((name) => ({ name })) });

describe('isSeniorCouple', () => {
  it('flags a same-surname pair (a senior couple)', () => {
    expect(isSeniorCouple(comp('Reese, Lambert', 'Reese, Carol'))).toBe(true);
  });
  it('does not flag a young companionship (different surnames)', () => {
    expect(isSeniorCouple(comp('Smith, John', 'Doe, Mark'))).toBe(false);
  });
  it('does not flag a single missionary', () => {
    expect(isSeniorCouple(comp('Smith, John'))).toBe(false);
  });
  it('handles "Given Surname" name order too', () => {
    expect(isSeniorCouple(comp('Lambert Reese', 'Carol Reese'))).toBe(true);
  });
});

describe('baptismCardMissionaries', () => {
  it('drops senior couples and keeps the teaching companionship', () => {
    const senior = comp('Reese, Lambert', 'Reese, Carol');
    const young = comp('Smith, John', 'Doe, Mark');
    expect(baptismCardMissionaries([senior, young])).toEqual([young]);
  });

  it('caps at one companionship per card', () => {
    const a = comp('Smith, John', 'Doe, Mark');
    const b = comp('Brown, Pat', 'Green, Lee');
    expect(baptismCardMissionaries([a, b])).toEqual([a]);
  });

  it('returns nothing when only a senior couple serves the unit', () => {
    expect(baptismCardMissionaries([comp('Reese, Lambert', 'Reese, Carol')])).toEqual([]);
  });
});
