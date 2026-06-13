// Pure-logic tests for the single-note model (item 8): the durable member_notes row WINS; a legacy
// member_comments thread is FOLDED into one text so nothing is lost before the first edit.
// Mirrored in Swift (NotesIndexTests) and Kotlin (NotesIndexTest).

import { describe, it, expect } from 'vitest';
import { buildNotesIndex, foldComments } from '../logic/notes';

describe('foldComments (legacy thread → one text)', () => {
  it('concatenates oldest→newest with author + date prefixes', () => {
    const text = foldComments([
      { body: 'second', author_name: 'Bob', created_at: '2026-06-08T10:00:00Z' },
      { body: 'first', author_name: 'Ann', created_at: '2026-06-07T10:00:00Z' },
    ]);
    const lines = text.split('\n');
    expect(lines[0]).toMatch(/^Ann · /);
    expect(lines[1]).toBe('first');
    expect(text).toContain('second');
    // first appears before second (chronological)
    expect(text.indexOf('first')).toBeLessThan(text.indexOf('second'));
  });

  it('falls back to email when no name, and to bare body when neither', () => {
    expect(foldComments([{ body: 'hi', author_email: 'x@y.z', created_at: '2026-06-01T00:00:00Z' }]))
      .toMatch(/^x@y\.z · /);
    expect(foldComments([{ body: 'bare' }])).toBe('bare');
  });

  it('skips blank bodies, returns "" for an empty thread', () => {
    expect(foldComments([{ body: '   ' }, { body: '' }])).toBe('');
    expect(foldComments([])).toBe('');
  });
});

describe('buildNotesIndex (single note wins; folds legacy thread)', () => {
  it('uses the durable single note over a folded thread', () => {
    const idx = buildNotesIndex(
      [{ member_person_uuid: 'a', note: 'the single note', updated_at: '2026-06-10T00:00:00Z' }],
      [{ member_person_uuid: 'a', body: 'old comment', created_at: '2026-06-01T00:00:00Z' }],
    );
    expect(idx['a'].text).toBe('the single note');
    expect(idx['a'].updatedAt).toBe('2026-06-10T00:00:00Z');
  });

  it('folds the legacy thread when there is no single note yet', () => {
    const idx = buildNotesIndex(
      [],
      [
        { member_person_uuid: 'b', body: 'c1', created_at: '2026-06-01T00:00:00Z' },
        { member_person_uuid: 'b', body: 'c2', created_at: '2026-06-02T00:00:00Z' },
      ],
    );
    expect(idx['b'].text).toContain('c1');
    expect(idx['b'].text).toContain('c2');
    expect(idx['b'].updatedAt).toBe('2026-06-02T00:00:00Z');
  });

  it('an explicit empty single note clears (does not resurrect the old thread)', () => {
    const idx = buildNotesIndex(
      [{ member_person_uuid: 'c', note: '', updated_at: '2026-06-10T00:00:00Z' }],
      [{ member_person_uuid: 'c', body: 'old', created_at: '2026-06-01T00:00:00Z' }],
    );
    expect(idx['c']).toBeUndefined();
  });

  it('skips rows without a uuid; empty inputs → empty index', () => {
    expect(buildNotesIndex([], [])).toEqual({});
    expect(buildNotesIndex([{ member_person_uuid: '', note: 'x' }], [])).toEqual({});
  });
});
