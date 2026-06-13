// Manual-member matching + merge logic (item 11): match by name WITHIN the same unit (suggest, never
// auto), remote is a FULL override, custom notes are preserved.

import { describe, it, expect } from 'vitest';
import {
  normalizeName, findMatch, mergeSuggestions, planMerge, mergedNote,
  type ManualMember,
} from '../logic/manualMembers';
import type { Member } from '../lib/member';

function manual(over: Partial<ManualMember> = {}): ManualMember {
  return { id: 'mm1', unit_name: 'Alpha Ward', name: 'John Smith', custom_notes: 'keep me', ...over };
}
function member(over: Partial<Record<string, unknown>> = {}): Member {
  return { person_uuid: 'p1', name: 'Smith, John', unit_name: 'Alpha Ward', kind: 'investigator', ...over };
}

describe('normalizeName', () => {
  it('folds "Surname, Given" and "Given Surname" to the same token set', () => {
    expect(normalizeName('Smith, John')).toBe(normalizeName('John Smith'));
    expect(normalizeName('  John   SMITH ')).toBe('john smith');
  });

  it('strips punctuation and is order-insensitive', () => {
    expect(normalizeName('Mary-Jane O\'Brien')).toBe(normalizeName('OBrien Mary-Jane'));
  });
});

describe('findMatch (by name within the same unit)', () => {
  it('matches a real member with the same normalized name in the same unit', () => {
    const m = findMatch(manual(), [member()]);
    expect(m?.['person_uuid']).toBe('p1');
  });

  it('does NOT match across different units (even with the same name)', () => {
    expect(findMatch(manual({ unit_name: 'Alpha Ward' }), [member({ unit_name: 'Beta Ward' })])).toBeNull();
  });

  it('matches on unit_id when both sides have it (ignores name drift in unit_name)', () => {
    const mm = manual({ unit_id: 'u-1', unit_name: 'old name' });
    const real = member({ unit_id: 'u-1', unit_name: 'new name' });
    expect(findMatch(mm, [real])?.['person_uuid']).toBe('p1');
  });

  it('never matches an already-merged manual member', () => {
    expect(findMatch(manual({ merged_at: '2026-06-12T00:00:00Z' }), [member()])).toBeNull();
  });

  it('skips real members without a person_uuid', () => {
    expect(findMatch(manual(), [member({ person_uuid: null })])).toBeNull();
  });
});

describe('mergeSuggestions', () => {
  it('returns one suggestion per matched, unmerged manual member', () => {
    const manuals = [manual({ id: 'a' }), manual({ id: 'b', name: 'Nobody Here' })];
    const sugs = mergeSuggestions(manuals, [member()]);
    expect(sugs).toHaveLength(1);
    expect(sugs[0].manual.id).toBe('a');
  });
});

describe('planMerge + mergedNote (remote overrides; notes preserved)', () => {
  it('plan carries the real uuid + the preserved manual note', () => {
    const plan = planMerge(manual({ custom_notes: '  keep this  ' }), member());
    expect(plan).toEqual({ personUuid: 'p1', preservedNote: 'keep this', manualId: 'mm1' });
  });

  it('mergedNote preserves notes: empty existing → preserved alone', () => {
    expect(mergedNote('', 'preserved')).toBe('preserved');
  });

  it('mergedNote appends preserved under a divider when both exist', () => {
    expect(mergedNote('existing', 'preserved')).toBe('existing\n\npreserved');
  });

  it('mergedNote is idempotent (re-merge does not duplicate)', () => {
    expect(mergedNote('existing\n\npreserved', 'preserved')).toBe('existing\n\npreserved');
  });

  it('a preserved-empty merge keeps the existing note unchanged', () => {
    expect(mergedNote('existing', '   ')).toBe('existing');
  });
});
