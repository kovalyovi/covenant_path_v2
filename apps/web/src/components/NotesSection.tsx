// ONE editable leader note per member (item 8) — replaces the old comment thread. RLS-scoped to
// people you can see (same policy as members). Shown in FULL; edited INLINE when the note/edit
// affordance is tapped (no separate "Edit" button). The durable note lives in `member_notes`; a
// member with only legacy `member_comments` shows the folded thread until the first save, which then
// writes the single field. React port — mirrors the native single-note editors.

import { useEffect, useRef, useState } from 'react';
import { supabase } from '../lib/supabase';
import { useDashboard } from '../hooks/useDashboard';
import type { Member } from '../lib/member';
import { foldComments, type NoteRow } from '../logic/notes';
import { SectionCard } from './ui';
import { CardSkeleton } from './Skeletons';
import { useToast } from './Toast';

/** Load + edit a single note for one member. `autoEdit` opens straight into edit mode (used by the
 *  main-screen long-press path). */
export function NotesSection({ member, autoEdit = false }: { member: Member; autoEdit?: boolean }) {
  const toast = useToast();
  const { reloadNotes } = useDashboard();
  const uuid = member['person_uuid'] != null ? String(member['person_uuid']) : '';
  const [note, setNote] = useState<string | null>(null); // null = loading
  const [editing, setEditing] = useState(autoEdit);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);

  async function load() {
    if (!uuid) {
      setNote('');
      return;
    }
    // The durable single note wins; fall back to the folded legacy thread.
    const { data: single } = await supabase
      .from('member_notes')
      .select('note')
      .eq('member_person_uuid', uuid)
      .maybeSingle();
    if (single && typeof single.note === 'string' && single.note.trim()) {
      setNote(single.note);
      return;
    }
    const { data: cmts } = await supabase
      .from('member_comments')
      .select('body, author_name, author_email, created_at')
      .eq('member_person_uuid', uuid)
      .order('created_at');
    setNote(foldComments((cmts ?? []) as NoteRow[]));
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uuid]);

  // When entering edit mode, seed the draft with the current note and focus the field.
  useEffect(() => {
    if (editing) {
      setDraft(note ?? '');
      // focus after paint
      requestAnimationFrame(() => taRef.current?.focus());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing]);

  async function save() {
    if (!uuid) return;
    const body = draft.trim();
    setSaving(true);
    try {
      const email = (await supabase.auth.getUser()).data.user?.email ?? '';
      const { error } = await supabase.from('member_notes').upsert(
        {
          stake_id: member['stake_id'],
          unit_id: member['unit_id'],
          member_person_uuid: uuid,
          note: body,
          updated_by: email,
          updated_at: new Date().toISOString(),
        },
        { onConflict: 'stake_id,member_person_uuid' },
      );
      if (error) throw error;
      setNote(body);
      setEditing(false);
      void reloadNotes(); // main-screen rows show the note in full — keep their index in step
    } catch (e) {
      toast.show({ message: `Could not save note: ${e instanceof Error ? e.message : e}` });
    } finally {
      setSaving(false);
    }
  }

  if (!uuid) return null;

  return (
    <SectionCard title="Notes" icon="feedback">
      {note == null ? (
        <CardSkeleton lines={2} />
      ) : editing ? (
        <div className="stack" style={{ gap: 8 }}>
          <textarea
            ref={taRef}
            className="textarea"
            rows={5}
            placeholder="Write a note about this member…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="row" style={{ gap: 8, justifyContent: 'flex-end' }}>
            <button
              type="button"
              className="btn btn--text"
              disabled={saving}
              onClick={() => {
                setEditing(false);
                setDraft(note ?? '');
              }}
            >
              Cancel
            </button>
            <button type="button" className="btn btn--filled" disabled={saving} onClick={save}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      ) : (
        // Tap the note (or the placeholder) to edit — no separate Edit button.
        <button
          type="button"
          className="note-edit-surface"
          aria-label={note ? 'Edit note' : 'Add a note'}
          onClick={() => setEditing(true)}
        >
          {note ? (
            <p className="note-body" style={{ whiteSpace: 'pre-wrap' }}>{note}</p>
          ) : (
            <p className="muted">Tap to add a note…</p>
          )}
        </button>
      )}
    </SectionCard>
  );
}
