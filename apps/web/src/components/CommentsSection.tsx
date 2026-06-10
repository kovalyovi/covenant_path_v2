// Leader notes on a member (RLS-scoped to people you can see). Read + add. The DB enforces who can
// see what across scope boundaries. React port of `_CommentsSection` (person_detail_page.dart).

import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { useDashboard } from '../hooks/useDashboard';
import type { Member } from '../lib/member';
import { fmtDateTime } from '../logic/dates';
import { SectionCard, IconButton } from './ui';
import { CardSkeleton } from './Skeletons';
import { useToast } from './Toast';

interface Comment {
  author_email?: string;
  author_name?: string;
  body?: string;
  created_at?: string;
}

export function CommentsSection({ member }: { member: Member }) {
  const toast = useToast();
  const { reloadNotes } = useDashboard();
  const uuid = member['person_uuid'] != null ? String(member['person_uuid']) : '';
  const [comments, setComments] = useState<Comment[] | null>(null);
  const [text, setText] = useState('');
  const [posting, setPosting] = useState(false);

  async function load() {
    if (!uuid) {
      setComments([]);
      return;
    }
    const { data } = await supabase
      .from('member_comments')
      .select('author_email, author_name, body, created_at')
      .eq('member_person_uuid', uuid)
      .order('created_at');
    setComments((data ?? []) as Comment[]);
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uuid]);

  async function post() {
    const body = text.trim();
    if (!body || !uuid) return;
    setPosting(true);
    try {
      const { error } = await supabase.from('member_comments').insert({
        stake_id: member['stake_id'],
        unit_id: member['unit_id'],
        member_person_uuid: uuid,
        author_email: (await supabase.auth.getUser()).data.user?.email ?? '',
        body,
      });
      if (error) throw error;
      setText('');
      await load();
      void reloadNotes(); // list rows show the newest note — keep their index in step
    } catch (e) {
      toast.show({ message: `Could not post note: ${e instanceof Error ? e.message : e}` });
    } finally {
      setPosting(false);
    }
  }

  if (!uuid) return null;

  return (
    <SectionCard title="Notes" icon="feedback">
      {comments == null ? (
        <CardSkeleton lines={2} />
      ) : comments.length === 0 ? (
        <p className="muted">No notes yet.</p>
      ) : (
        <div className="stack">
          {comments.map((c, i) => (
            <div key={i} style={{ padding: '6px 0' }}>
              <p>{c.body ?? ''}</p>
              <p className="small muted" style={{ marginTop: 2 }}>
                {(c.author_name ?? c.author_email ?? '')} · {c.created_at ? fmtDateTime(c.created_at) : ''}
              </p>
              <hr className="divider" style={{ margin: '8px 0 0' }} />
            </div>
          ))}
        </div>
      )}
      <div className="row" style={{ marginTop: 8, alignItems: 'flex-end' }}>
        <label className="field" style={{ flex: 1 }}>
          <span className="visually-hidden">Add a note</span>
          <textarea
            className="textarea"
            rows={1}
            placeholder="Add a note…"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        {posting ? (
          <span className="spinner" style={{ margin: 10 }} aria-label="Posting" role="status" />
        ) : (
          <IconButton icon="send" label="Post note" onClick={post} />
        )}
      </div>
    </SectionCard>
  );
}
