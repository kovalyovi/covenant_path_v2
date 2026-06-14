// Notes THREAD for one member (user feedback): multiple timestamped entries any in-scope unit leader
// can ADD, EDIT, and DELETE (individual + all). Backed by member_comments (RLS: a leader of the
// member's stake/unit; migration 0054 widened edit/delete to all in-scope leaders). Newest first.

import { useEffect, useRef, useState } from 'react';
import { supabase } from '../lib/supabase';
import { useDashboard } from '../hooks/useDashboard';
import type { Member } from '../lib/member';
import { fmtDateTime } from '../logic/dates';
import { SectionCard, Button } from './ui';
import { CardSkeleton } from './Skeletons';
import { useToast } from './Toast';

interface Entry {
  id: string;
  body: string;
  author_name?: string | null;
  author_email?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export function NotesSection({ member, autoEdit = false }: { member: Member; autoEdit?: boolean }) {
  const toast = useToast();
  const { reloadNotes } = useDashboard();
  const uuid = member['person_uuid'] != null ? String(member['person_uuid']) : '';
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState('');
  const addRef = useRef<HTMLTextAreaElement>(null);

  async function load() {
    if (!uuid) { setEntries([]); return; }
    const { data } = await supabase
      .from('member_comments')
      .select('id, body, author_name, author_email, created_at, updated_at')
      .eq('member_person_uuid', uuid)
      .order('created_at', { ascending: false });
    setEntries((data ?? []) as Entry[]);
  }
  useEffect(() => {
    void load();
    if (autoEdit) requestAnimationFrame(() => addRef.current?.focus());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uuid]);

  async function currentEmail(): Promise<string> {
    return (await supabase.auth.getUser()).data.user?.email ?? '';
  }

  async function add() {
    const body = draft.trim();
    if (!body || !uuid) return;
    setBusy(true);
    try {
      const email = await currentEmail();
      const { error } = await supabase.from('member_comments').insert({
        stake_id: member['stake_id'], unit_id: member['unit_id'], member_person_uuid: uuid,
        author_email: email, author_name: email, body,
      });
      if (error) throw error;
      setDraft('');
      await load();
      void reloadNotes();
    } catch (e) {
      toast.show({ message: `Could not add note: ${e instanceof Error ? e.message : e}` });
    } finally { setBusy(false); }
  }

  async function saveEdit(id: string) {
    const body = editDraft.trim();
    if (!body) return;
    setBusy(true);
    try {
      const email = await currentEmail();
      const { error } = await supabase.from('member_comments')
        .update({ body, updated_at: new Date().toISOString(), updated_by: email }).eq('id', id);
      if (error) throw error;
      setEditId(null);
      await load();
      void reloadNotes();
    } catch (e) {
      toast.show({ message: `Could not save: ${e instanceof Error ? e.message : e}` });
    } finally { setBusy(false); }
  }

  async function del(id: string) {
    setBusy(true);
    try {
      const { error } = await supabase.from('member_comments').delete().eq('id', id);
      if (error) throw error;
      await load();
      void reloadNotes();
    } catch (e) {
      toast.show({ message: `Could not delete: ${e instanceof Error ? e.message : e}` });
    } finally { setBusy(false); }
  }

  async function clearAll() {
    if (!uuid || !(entries && entries.length)) return;
    if (!window.confirm('Delete ALL notes for this person? This cannot be undone.')) return;
    setBusy(true);
    try {
      const { error } = await supabase.from('member_comments').delete().eq('member_person_uuid', uuid);
      if (error) throw error;
      await load();
      void reloadNotes();
    } catch (e) {
      toast.show({ message: `Could not clear: ${e instanceof Error ? e.message : e}` });
    } finally { setBusy(false); }
  }

  if (!uuid) return null;
  const linkBtn = { border: 'none', background: 'none', color: 'var(--primary)', cursor: 'pointer', font: 'inherit', padding: 0 } as const;

  return (
    <SectionCard
      title="Notes"
      icon="feedback"
      trailing={entries && entries.length > 0
        ? <button type="button" style={{ ...linkBtn, color: 'var(--error)' }} onClick={clearAll}>Clear all</button>
        : undefined}
    >
      {/* Add a new entry (always available). */}
      <div className="stack" style={{ gap: 8 }}>
        <textarea
          ref={addRef}
          className="textarea"
          rows={2}
          placeholder="Add a note…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <Button variant="filled" disabled={busy || !draft.trim()} onClick={add}>Add note</Button>
        </div>
      </div>
      <hr className="divider" />

      {entries == null ? (
        <CardSkeleton lines={2} />
      ) : entries.length === 0 ? (
        <p className="muted">No notes yet.</p>
      ) : (
        <div className="stack" style={{ gap: 14 }}>
          {entries.map((e) => (
            <div key={e.id} className="stack" style={{ gap: 4 }}>
              <div className="row tiny muted" style={{ justifyContent: 'space-between', gap: 8 }}>
                <span style={{ minWidth: 0 }}>
                  {(e.author_name || e.author_email || 'Leader')} · {fmtDateTime(e.created_at)}{e.updated_at ? ' (edited)' : ''}
                </span>
                {editId !== e.id && (
                  <span className="row" style={{ gap: 10, flexShrink: 0 }}>
                    <button type="button" style={linkBtn} onClick={() => { setEditId(e.id); setEditDraft(e.body); }}>Edit</button>
                    <button type="button" style={{ ...linkBtn, color: 'var(--error)' }} onClick={() => del(e.id)}>Delete</button>
                  </span>
                )}
              </div>
              {editId === e.id ? (
                <div className="stack" style={{ gap: 8 }}>
                  <textarea className="textarea" rows={3} value={editDraft} onChange={(ev) => setEditDraft(ev.target.value)} />
                  <div className="row" style={{ gap: 8, justifyContent: 'flex-end' }}>
                    <button type="button" className="btn btn--text" disabled={busy} onClick={() => setEditId(null)}>Cancel</button>
                    <button type="button" className="btn btn--filled" disabled={busy} onClick={() => saveEdit(e.id)}>Save</button>
                  </div>
                </div>
              ) : (
                <p className="note-body" style={{ whiteSpace: 'pre-wrap' }}>{e.body}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}
