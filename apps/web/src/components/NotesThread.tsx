// Chat-style notes thread for a member, embedded in Baptisms cards (user feedback 2026-07-19:
// notes are the CONVERSATION about a person — show them as a prominent chat thread, not a small
// italic line, and make adding one effortless). Entries render as chat bubbles (author + relative
// time, readable body size), oldest→newest like a conversation, capped to the latest few with an
// expander. The "Add note" affordance follows the pointer: on hover-capable devices it appears on
// card hover/focus; on touch, tapping the card reveals it (the card root toggles `.is-revealed`).
// Data comes from the dashboard-wide thread map (member_comments, RLS-scoped); adds insert directly
// and refresh that shared map, so every surface (table NoteLine, person detail) stays in step.

import { useRef, useState } from 'react';
import { supabase } from '../lib/supabase';
import { useDashboard } from '../hooks/useDashboard';
import type { Member } from '../lib/member';
import { ago } from '../logic/dates';
import { Icon } from './Icon';
import { Button } from './ui';
import { useToast } from './Toast';

const SHOWN = 3; // latest bubbles shown collapsed; the expander reveals the rest

/** Display name for a bubble: prefer the human name, fall back to the email's mailbox. */
function authorLabel(name?: string | null, email?: string | null): string {
  if (name && !name.includes('@')) return name;
  const source = name || email || 'Leader';
  return source.includes('@') ? source.split('@')[0] : source;
}

export function NotesThread({ member }: { member: Member }) {
  const toast = useToast();
  const { threads, reloadNotes } = useDashboard();
  const uuid = member['person_uuid'] != null ? String(member['person_uuid']) : '';
  const [expanded, setExpanded] = useState(false);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  if (!uuid) return null;
  const newestFirst = threads[uuid] ?? [];
  const chrono = [...newestFirst].reverse(); // chat order: oldest at the top, newest last
  const visible = expanded ? chrono : chrono.slice(-SHOWN);
  const hidden = chrono.length - visible.length;

  async function add() {
    const body = draft.trim();
    if (!body) return;
    setBusy(true);
    try {
      const email = (await supabase.auth.getUser()).data.user?.email ?? '';
      const { error } = await supabase.from('member_comments').insert({
        stake_id: member['stake_id'], unit_id: member['unit_id'], member_person_uuid: uuid,
        author_email: email, author_name: email, body,
      });
      if (error) throw error;
      setDraft('');
      setAdding(false);
      await reloadNotes();
    } catch (e) {
      toast.show({ message: `Could not add note: ${e instanceof Error ? e.message : e}` });
    } finally { setBusy(false); }
  }

  return (
    <div className="note-thread" style={{ marginTop: 10 }}>
      {chrono.length === 0 && !adding && (
        <p className="tiny muted" style={{ margin: 0 }}>No notes yet.</p>
      )}
      {hidden > 0 && (
        <button type="button" className="note-thread__more" onClick={() => setExpanded(true)}>
          Show {hidden} earlier note{hidden === 1 ? '' : 's'}
        </button>
      )}
      {visible.map((e, i) => (
        <div key={i} className="note-bubble">
          <span className="note-bubble__meta">
            {authorLabel(e.author_name, e.author_email)} · {ago(e.created_at)}
          </span>
          <span className="note-bubble__body">{e.body}</span>
        </div>
      ))}

      {adding ? (
        <div className="stack" style={{ gap: 8, marginTop: 6 }}>
          <textarea
            ref={inputRef}
            className="textarea"
            rows={2}
            placeholder="Add a note — a concern, a detail, a next step…"
            value={draft}
            onChange={(ev) => setDraft(ev.target.value)}
            onKeyDown={(ev) => {
              if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) void add();
              if (ev.key === 'Escape') setAdding(false);
            }}
          />
          <div className="row" style={{ gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" className="btn btn--text" disabled={busy} onClick={() => setAdding(false)}>
              Cancel
            </button>
            <Button variant="filled" disabled={busy || !draft.trim()} onClick={add}>Add note</Button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="note-thread__add"
          onClick={() => {
            setAdding(true);
            requestAnimationFrame(() => inputRef.current?.focus());
          }}
        >
          <Icon name="note" size={14} color="var(--primary)" /> Add note
        </button>
      )}
    </div>
  );
}
