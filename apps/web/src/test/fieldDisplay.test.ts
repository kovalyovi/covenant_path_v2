// The CLIENT DISPLAY CONTRACT (item 5): a field value maps to exactly one of three states —
//   • a real value          → 'value', shown verbatim, no warning
//   • "N/A"                  → 'na', not eligible, shown quietly, NEVER a warning
//   • the needs-profile-api sentinel OR null/empty → 'issue', a DATA ISSUE rendered with a ⚠
// Critically: the sentinel AND null/empty are treated THE SAME (both 'issue'), and the raw sentinel
// string is NEVER surfaced to a leader (only an admin sees it as diagnostic text).

import { describe, it, expect } from 'vitest';
import { fieldDisplay, isDataIssue } from '../logic/fieldDisplay';
import { NEEDS_PROFILE } from '../lib/member';

describe('fieldDisplay — three-way contract', () => {
  it('a real value is shown verbatim, never a warning', () => {
    for (const v of ['Yes', 'No', 'Active', 'Expired', '6 Feb 2026']) {
      expect(fieldDisplay(v)).toEqual({ status: 'value', text: v, warn: false });
    }
  });

  it('N/A is quiet — never a warning (not eligible)', () => {
    const r = fieldDisplay('N/A');
    expect(r.status).toBe('na');
    expect(r.warn).toBe(false);
    expect(r.text).toBe('N/A');
    // case / whitespace tolerant
    expect(fieldDisplay(' n/a ').status).toBe('na');
    expect(fieldDisplay(' n/a ').warn).toBe(false);
  });

  it('the needs-profile-api sentinel is a DATA ISSUE (⚠), never the raw string for a leader', () => {
    const r = fieldDisplay(NEEDS_PROFILE, false);
    expect(r.status).toBe('issue');
    expect(r.warn).toBe(true);
    expect(r.text).toBe(''); // leader never sees the techy sentinel
  });

  it('a blocked sentinel is a DATA ISSUE too', () => {
    const r = fieldDisplay('blocked: insufficient calling access', false);
    expect(r.status).toBe('issue');
    expect(r.warn).toBe(true);
    expect(r.text).toBe('');
  });

  it('null / undefined / empty are treated the SAME as the sentinel (⚠ data issue)', () => {
    for (const v of [null, undefined, '', '   ']) {
      const r = fieldDisplay(v);
      expect(r.status).toBe('issue');
      expect(r.warn).toBe(true);
      expect(r.text).toBe('');
    }
  });

  it('an admin sees the raw sentinel as diagnostic text (still a warning), an empty value has none', () => {
    expect(fieldDisplay(NEEDS_PROFILE, true)).toEqual({ status: 'issue', text: NEEDS_PROFILE, warn: true });
    expect(fieldDisplay('blocked: x', true)).toEqual({ status: 'issue', text: 'blocked: x', warn: true });
    // an empty value carries no techy string, so even an admin sees no diagnostic text
    expect(fieldDisplay('', true)).toEqual({ status: 'issue', text: '', warn: true });
  });
});

describe('isDataIssue', () => {
  it('true for the sentinel and for null/empty; false for N/A and real values', () => {
    expect(isDataIssue(NEEDS_PROFILE)).toBe(true);
    expect(isDataIssue('')).toBe(true);
    expect(isDataIssue(null)).toBe(true);
    expect(isDataIssue('N/A')).toBe(false); // not eligible, NOT a data issue
    expect(isDataIssue('Yes')).toBe(false);
    expect(isDataIssue('No')).toBe(false);
    expect(isDataIssue('Active')).toBe(false);
  });
});
