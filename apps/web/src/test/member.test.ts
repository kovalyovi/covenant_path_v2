// The sentinel display mapping (admin-only techy language): backend sentinels
// ('needs-profile-api' / 'blocked: insufficient calling access') must show raw ONLY to admins and
// friendly text to regular leaders — they must never leak into a leader's table/detail cell.

import { describe, it, expect } from 'vitest';
import { isSentinel, displayFieldValue, NEEDS_PROFILE } from '../lib/member';

describe('isSentinel', () => {
  it('recognizes the backend sentinels', () => {
    expect(isSentinel(NEEDS_PROFILE)).toBe(true);
    expect(isSentinel('blocked: insufficient calling access')).toBe(true);
    expect(isSentinel('blocked: anything')).toBe(true);
  });

  it('treats real values (and empties) as NOT sentinels', () => {
    expect(isSentinel('Yes')).toBe(false);
    expect(isSentinel('No')).toBe(false);
    expect(isSentinel('Active')).toBe(false);
    expect(isSentinel('6 Feb 2026')).toBe(false);
    expect(isSentinel('')).toBe(false);
    expect(isSentinel(null)).toBe(false);
    expect(isSentinel(undefined)).toBe(false);
  });
});

describe('displayFieldValue (admin-only techy language)', () => {
  it('shows the raw sentinel to admins (so they can diagnose)', () => {
    expect(displayFieldValue(NEEDS_PROFILE, true)).toBe(NEEDS_PROFILE);
    expect(displayFieldValue('blocked: insufficient calling access', true)).toBe(
      'blocked: insufficient calling access',
    );
  });

  it('hides the sentinel from regular leaders with friendly text', () => {
    expect(displayFieldValue(NEEDS_PROFILE, false)).toBe('Not available yet');
    expect(displayFieldValue('blocked: insufficient calling access', false)).toBe('Not available yet');
    // the dense-table variant blanks to an em dash instead
    expect(displayFieldValue(NEEDS_PROFILE, false, '—')).toBe('—');
  });

  it('passes real values through unchanged for both audiences', () => {
    for (const admin of [true, false]) {
      expect(displayFieldValue('Yes', admin)).toBe('Yes');
      expect(displayFieldValue('Active', admin)).toBe('Active');
      expect(displayFieldValue('6 Feb 2026', admin)).toBe('6 Feb 2026');
      expect(displayFieldValue('', admin)).toBe('');
    }
  });
});
