// NotesThread (Baptisms chat-style notes, 2026-07-19): entries render as READABLE chat bubbles
// (author + relative time + body — not the old one-line italic), oldest→newest with the latest 3
// shown and an expander for the rest, and an in-card "Add note" flow that inserts a member_comments
// row and refreshes the shared thread map.

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const insert = vi.fn(async (_row: Record<string, unknown>) => ({ error: null }));
const reloadNotes = vi.fn(async () => {});
vi.mock('../lib/supabase', () => ({
  supabase: {
    from: () => ({ insert }),
    auth: { getUser: async () => ({ data: { user: { email: 'leader@example.org' } } }) },
  },
}));

const entry = (body: string, daysAgo: number, author = 'Sister Lopez') => ({
  body,
  author_name: author,
  author_email: 'x@y.org',
  created_at: new Date(Date.now() - daysAgo * 86400_000).toISOString(),
});
let threads: Record<string, ReturnType<typeof entry>[]> = {};
vi.mock('../hooks/useDashboard', () => ({ useDashboard: () => ({ threads, reloadNotes }) }));

import { NotesThread } from '../components/NotesThread';
import { ToastProvider } from '../components/Toast';
import type { Member } from '../lib/member';

const member = { person_uuid: 'u1', stake_id: 's1', unit_id: 'un1' } as unknown as Member;

function renderThread() {
  return render(
    <ToastProvider>
      <NotesThread member={member} />
    </ToastProvider>,
  );
}

describe('NotesThread', () => {
  it('renders entries as bubbles with author and body (newest last, chat order)', () => {
    threads = { u1: [entry('Newest note', 0), entry('Older note', 2)] }; // map is newest-first
    renderThread();
    const bodies = [...document.querySelectorAll('.note-bubble__body')].map((n) => n.textContent);
    expect(bodies).toEqual(['Older note', 'Newest note']);
    expect(screen.getAllByText(/Sister Lopez ·/)).toHaveLength(2);
  });

  it('caps at 3 bubbles with a "Show earlier" expander', () => {
    threads = { u1: [entry('n4', 0), entry('n3', 1), entry('n2', 2), entry('n1', 3)] };
    renderThread();
    expect(document.querySelectorAll('.note-bubble')).toHaveLength(3);
    fireEvent.click(screen.getByText('Show 1 earlier note'));
    expect(document.querySelectorAll('.note-bubble')).toHaveLength(4);
  });

  it('"Add note" reveals the input and inserts a member_comments row', async () => {
    threads = { u1: [] };
    renderThread();
    expect(screen.getByText('No notes yet.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Add note/ }));
    const input = screen.getByPlaceholderText(/Add a note/);
    fireEvent.change(input, { target: { value: 'Needs a ride Sunday' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add note' }));
    await waitFor(() => expect(insert).toHaveBeenCalledOnce());
    expect(insert.mock.calls[0]![0]).toMatchObject({
      member_person_uuid: 'u1', stake_id: 's1', unit_id: 'un1',
      author_email: 'leader@example.org', body: 'Needs a ride Sunday',
    });
    await waitFor(() => expect(reloadNotes).toHaveBeenCalled());
  });
});
