// Device preference: the notes show/hide toggle. (Filter/sort/view state now lives in the URL query
// string — see usePersistentState — so there's no longer a "remember" switch or view-pref storage.)

import { describe, it, expect, beforeEach } from 'vitest';
import { getShowNotes, setShowNotes } from '../lib/prefs';

beforeEach(() => {
  localStorage.clear();
});

describe('notes show/hide', () => {
  it('defaults to SHOW (true)', () => {
    expect(getShowNotes()).toBe(true);
  });

  it('persists across reads on this device', () => {
    setShowNotes(false);
    expect(getShowNotes()).toBe(false);
    setShowNotes(true);
    expect(getShowNotes()).toBe(true);
  });
});
