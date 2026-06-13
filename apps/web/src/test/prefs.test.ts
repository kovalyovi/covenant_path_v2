// Local-only preferences (item 9): the global "remember" switch gates ALL view-pref persistence and
// the notes show/hide default. Pure localStorage logic.

import { describe, it, expect, beforeEach } from 'vitest';
import {
  getRemember, setRemember, getShowNotes, setShowNotes,
  saveViewPref, loadViewPref, clearViewPrefs,
} from '../lib/prefs';

beforeEach(() => {
  localStorage.clear();
});

describe('remember switch', () => {
  it('defaults ON', () => {
    expect(getRemember()).toBe(true);
  });

  it('persists and reflects the off state', () => {
    setRemember(false);
    expect(getRemember()).toBe(false);
    setRemember(true);
    expect(getRemember()).toBe(true);
  });

  it('turning it off clears already-persisted view prefs (but keeps the switch)', () => {
    saveViewPref('table.sortCol', 3);
    expect(loadViewPref('table.sortCol', null)).toBe(3);
    setRemember(false);
    // remember=false → loadViewPref returns the fallback regardless, AND the stored value is gone
    setRemember(true); // turn back on to read raw storage through loadViewPref
    expect(loadViewPref('table.sortCol', null)).toBe(null);
  });
});

describe('view prefs are gated by remember', () => {
  it('saves + loads when remember is on', () => {
    saveViewPref('needs.ward', 'Testvale 1st Ward');
    expect(loadViewPref('needs.ward', null)).toBe('Testvale 1st Ward');
  });

  it('does NOT persist when remember is off; loads fall back', () => {
    setRemember(false);
    saveViewPref('needs.ward', 'X');
    expect(loadViewPref('needs.ward', 'fallback')).toBe('fallback');
  });

  it('round-trips arrays/objects (Set serialized as array elsewhere)', () => {
    saveViewPref('gh.orgs', ['wml', 'eq']);
    expect(loadViewPref<string[]>('gh.orgs', [])).toEqual(['wml', 'eq']);
  });

  it('clearViewPrefs forgets view prefs + notes but keeps the remember switch', () => {
    setRemember(true);
    saveViewPref('kpis.period', 'year');
    setShowNotes(false);
    clearViewPrefs();
    expect(loadViewPref('kpis.period', 'month')).toBe('month');
    expect(getRemember()).toBe(true); // switch survives
  });
});

describe('notes show/hide', () => {
  it('defaults to SHOW (true)', () => {
    expect(getShowNotes()).toBe(true);
  });

  it('persists when remember is on', () => {
    setShowNotes(false);
    expect(getShowNotes()).toBe(false);
  });

  it('is not persisted while remember is off (always defaults to show)', () => {
    setRemember(false);
    setShowNotes(false); // no-op while off
    expect(getShowNotes()).toBe(true);
  });
});
