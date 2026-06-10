// Pure-logic tests for the notes index (latest leader note per member shown on list rows).
// Mirrored in Swift (NotesIndexTests) and Kotlin (NotesIndexTest).

import { describe, it, expect } from 'vitest';
import { buildNotesIndex } from '../logic/notes';

describe('buildNotesIndex', () => {
  it('keeps the newest note per member and counts the rest', () => {
    const idx = buildNotesIndex([
      { member_person_uuid: 'a', body: 'older', created_at: '2026-06-01T10:00:00+00:00' },
      { member_person_uuid: 'a', body: 'newest', created_at: '2026-06-09T10:00:00+00:00' },
      { member_person_uuid: 'a', body: 'middle', created_at: '2026-06-05T10:00:00+00:00' },
      { member_person_uuid: 'b', body: 'only one', created_at: '2026-06-02T10:00:00+00:00' },
    ]);
    expect(idx['a']).toEqual({ count: 3, latest: 'newest', latestAt: '2026-06-09T10:00:00+00:00' });
    expect(idx['b']).toEqual({ count: 1, latest: 'only one', latestAt: '2026-06-02T10:00:00+00:00' });
  });

  it('orders correctly regardless of row order (DB order is unspecified)', () => {
    const rows = [
      { member_person_uuid: 'a', body: 'second', created_at: '2026-06-08T10:00:00+00:00' },
      { member_person_uuid: 'a', body: 'first', created_at: '2026-06-07T10:00:00+00:00' },
    ];
    expect(buildNotesIndex(rows)['a'].latest).toBe('second');
    expect(buildNotesIndex(rows.reverse())['a'].latest).toBe('second');
  });

  it('skips rows without a uuid or with a blank body', () => {
    const idx = buildNotesIndex([
      { member_person_uuid: '', body: 'no uuid', created_at: '2026-06-01T00:00:00Z' },
      { member_person_uuid: 'a', body: '   ', created_at: '2026-06-01T00:00:00Z' },
      { member_person_uuid: 'a', body: null, created_at: '2026-06-01T00:00:00Z' },
      { member_person_uuid: null, body: 'x', created_at: '2026-06-01T00:00:00Z' },
    ]);
    expect(idx).toEqual({});
  });

  it('handles a missing created_at without crashing (counts, keeps a body)', () => {
    const idx = buildNotesIndex([
      { member_person_uuid: 'a', body: 'undated' },
      { member_person_uuid: 'a', body: 'dated', created_at: '2026-06-01T00:00:00Z' },
    ]);
    expect(idx['a'].count).toBe(2);
    expect(idx['a'].latest).toBe('dated');
  });
});
